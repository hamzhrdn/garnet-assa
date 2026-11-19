"""Rebuild data turunan Garnet dari RavenDB (desain bagian 3 dan 5).

Jalankan saat penulisan aplikasi dihentikan: pembacaan lintas halaman dan
penggantian lintas key bukan satu transaksi. Jika gagal saat menulis, jalankan
ulang. Hanya pola key desain di MANAGED_PATTERNS yang diganti/dibersihkan.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import os
from pathlib import Path
import sys


MANAGED_PATTERNS = (
    "paket:*", "order:*:resi", "lokasi:*:*", "tarif:*:*:*",
    "kurir:*:antar", "kurir:*:sukses", "rank:kurir:*",
    "pool:*:kendaraan_tersedia",
)


def required(document, field):
    value = document.get(field)
    if value is None or value == "":
        raise ValueError(f"Field wajib kosong: {field}")
    return value


def identifier(value):
    """Referensi RavenDB menjadi PK asli; jangan ubah kapitalisasi PK."""
    if value is None or value == "":
        return ""
    return str(value).rsplit("/", 1)[-1]


def day(value):
    return date.fromisoformat(str(value)[:10])


class Snapshot:
    def __init__(self, as_of):
        self.as_of = as_of
        self.hashes = {}
        self.sets = defaultdict(set)
        self.ranks = {}
        self.attempts = defaultdict(Counter)
        self.successes = defaultdict(Counter)
        self.tariff_versions = {}
        self.counts = Counter()

    def add_package(self, doc):
        resi = identifier(required(doc, "no_resi"))
        key = f"paket:{resi}"
        if key in self.hashes:
            raise ValueError(f"Resi duplikat: {resi}")
        events = doc.get("events") or []
        sequences = [int(required(event, "urutan_event")) for event in events]
        if any(n < 1 for n in sequences) or len(set(sequences)) != len(sequences):
            raise ValueError(f"Urutan event tidak valid: {resi}")
        latest = max(events, key=lambda e: int(e["urutan_event"])) if events else {}
        status = doc.get("status_terkini") or latest.get("status_pengiriman")
        if not status:
            raise ValueError(f"Status terkini kosong: {resi}")
        if latest and status != required(latest, "status_pengiriman"):
            raise ValueError(f"Status terkini berbeda dari event terakhir: {resi}")
        location = identifier(doc.get("id_lokasi_terkini", latest.get("id_lokasi")))
        self.hashes[key] = {
            "status": status,
            "urutan": max(sequences, default=0),
            "waktu": latest.get("waktu_event") or "",
            "id_lokasi": location,
            "id_kurir": identifier(latest.get("id_kurir")),
        }
        order = identifier(required(required(doc, "order"), "id_order"))
        self.sets[f"order:{order}:resi"].add(resi)
        if location:
            self.sets[f"lokasi:{location}:{status}"].add(resi)
        for event in events:
            event_status = required(event, "status_pengiriman")
            courier = identifier(event.get("id_kurir"))
            if event_status not in ("DITERIMA", "GAGAL_ANTAR"):
                continue
            if not courier:
                raise ValueError(f"Event upaya antar tanpa id_kurir: {resi}")
            timestamp = datetime.fromisoformat(required(event, "waktu_event"))
            month = timestamp.strftime("%Y%m")
            self.attempts[month][courier] += 1
            if event_status == "DITERIMA":
                self.successes[month][courier] += 1

    def add_tariff(self, doc):
        start = day(required(doc, "berlaku_mulai"))
        end = day(doc["berlaku_sampai"]) if doc.get("berlaku_sampai") else None
        if end is not None and end < start:
            raise ValueError("Rentang berlaku tarif tidak valid")
        if start > self.as_of or (end is not None and end < self.as_of):
            return
        service = required(doc, "jenis_layanan")
        origin = required(required(doc, "wilayah_asal"), "kode_wilayah")
        destination = required(required(doc, "wilayah_tujuan"), "kode_wilayah")
        key = f"tarif:{service}:{origin}:{destination}"
        tariff_id = identifier(required(doc, "id_tarif"))
        # Bila versi aktif bertumpuk, gunakan tanggal mulai paling baru.
        version = (start, tariff_id)
        if key in self.tariff_versions and version <= self.tariff_versions[key]:
            return
        self.tariff_versions[key] = version
        self.hashes[key] = {
            "id_tarif": tariff_id,
            "harga_per_kg": required(doc, "harga_per_kg"),
            "estimasi_waktu": required(doc, "estimasi_waktu"),
        }

    def add_vehicle(self, doc):
        if required(doc, "status_kendaraan") == "TERSEDIA":
            pool = identifier(required(doc, "id_lokasi_basis"))
            self.sets[f"pool:{pool}:kendaraan_tersedia"].add(
                identifier(required(doc, "no_polisi"))
            )

    def finish(self):
        quarterly_attempts = defaultdict(Counter)
        quarterly_successes = defaultdict(Counter)
        for month, attempts in self.attempts.items():
            successes = {courier: self.successes[month][courier] for courier in attempts}
            self.hashes[f"kurir:{month}:antar"] = dict(attempts)
            self.hashes[f"kurir:{month}:sukses"] = successes
            self.ranks[f"rank:kurir:{month}"] = {
                courier: 100 * successes[courier] / count
                for courier, count in attempts.items()
            }
            quarter = f"{month[:4]}Q{(int(month[4:]) - 1) // 3 + 1}"
            quarterly_attempts[quarter].update(attempts)
            quarterly_successes[quarter].update(successes)
        for quarter, attempts in quarterly_attempts.items():
            self.ranks[f"rank:kurir:{quarter}"] = {
                courier: 100 * quarterly_successes[quarter][courier] / count
                for courier, count in attempts.items()
            }

    @property
    def keys(self):
        return set(self.hashes) | set(self.sets) | set(self.ranks)


def read_collection(store, collection, batch_size):
    offset = 0
    while True:
        # Session baru per halaman menghindari limit request dan tracking membesar.
        with store.open_session() as session:
            page = list(session.advanced.raw_query(
                f"from '{collection}' order by id()", object_type=dict
            ).skip(offset).take(batch_size))
        yield from page
        if len(page) < batch_size:
            break
        offset += len(page)


def write_snapshot(client, snapshot, batch_size):
    # Ambil daftar lama sebelum mutasi: SCAN sambil DEL dapat melewatkan key.
    old_keys = set()
    for pattern in MANAGED_PATTERNS:
        old_keys.update(client.scan_iter(match=pattern, count=batch_size))
    with client.pipeline(transaction=False) as pipe:
        pending = 0

        def flush():
            nonlocal pending
            pipe.execute()
            pending = 0

        for kind, entries in (
            ("hash", snapshot.hashes), ("set", snapshot.sets), ("zset", snapshot.ranks)
        ):
            for key, values in entries.items():
                pipe.delete(key)
                pending += 1
                items = list(values.items()) if kind != "set" else sorted(values)
                for start in range(0, len(items), batch_size):
                    chunk = items[start:start + batch_size]
                    if kind == "hash":
                        pipe.hset(key, mapping=dict(chunk))
                    elif kind == "set":
                        pipe.sadd(key, *chunk)
                    else:
                        pipe.zadd(key, dict(chunk))
                    pending += 1
                    if pending >= batch_size:
                        flush()
        if pending:
            flush()
        stale = sorted(old_keys - snapshot.keys)
        for start in range(0, len(stale), batch_size):
            client.delete(*stale[start:start + batch_size])
    return len(stale)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 1, 1),
                        help="Tanggal tarif aktif, YYYY-MM-DD (default: 2026-01-01)")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true", help="Baca dan validasi tanpa menulis Garnet")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size harus positif")
    try:
        from dotenv import load_dotenv
        from ravendb import DocumentStore
        load_dotenv(Path(__file__).with_name(".env"))
        url = os.environ["RAVEN_URL"]
        database = os.environ["RAVEN_DATABASE"]
        snapshot = Snapshot(args.as_of)
        store = DocumentStore(urls=[url], database=database)
        certificate = os.getenv("RAVEN_CERT_PEM", "").strip()
        if certificate:
            store.certificate_pem_path = str(Path(certificate).resolve())
        try:
            store.initialize()
            for collection, consume in (
                ("Paket", snapshot.add_package),
                ("Tarif", snapshot.add_tariff),
                ("Kendaraan", snapshot.add_vehicle),
            ):
                for document in read_collection(store, collection, args.batch_size):
                    try:
                        consume(document)
                    except (ValueError, TypeError, KeyError) as error:
                        doc_id = document.get("@metadata", {}).get("@id", "ID tidak tersedia")
                        raise ValueError(f"{collection} ({doc_id}): {error}") from error
                    snapshot.counts[collection] += 1
                print(f"[OK] {collection}: {snapshot.counts[collection]:,} dokumen", flush=True)
        finally:
            store.close()
        snapshot.finish()
        print(f"[OK] Rencana: {len(snapshot.hashes):,} hash, "
              f"{len(snapshot.sets):,} set, {len(snapshot.ranks):,} sorted set; "
              f"tanggal tarif {args.as_of}")
        if args.dry_run:
            print("[DRY RUN] Garnet tidak diubah.")
            return 0
        if not snapshot.counts["Paket"] or not snapshot.counts["Tarif"] or not snapshot.counts["Kendaraan"]:
            raise ValueError("Collection sumber kosong; rebuild dibatalkan. Periksa database dan nama collection.")
        import redis
        client = redis.Redis(
            host=os.getenv("GARNET_HOST", "127.0.0.1"),
            port=int(os.getenv("GARNET_PORT", "6379")),
            password=os.getenv("GARNET_PASSWORD") or None,
            decode_responses=True, socket_connect_timeout=5, socket_timeout=30,
        )
        try:
            client.ping()
            removed = write_snapshot(client, snapshot, args.batch_size)
            print(f"[OK] {len(snapshot.keys):,} key dimuat; {removed:,} key usang dihapus.")
        finally:
            client.close()
        return 0
    except Exception as error:
        print(f"[GAGAL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
