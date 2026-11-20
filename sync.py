from collections import defaultdict, Counter
from datetime import date

import load_garnet as loader

class Snapshot:
    def __init__(self):
        self.hashes ={}
        self.sets = {}
        self.ranks = {}

    def hset(self, key, mapping):
        data = self.hashes.setdefault(key, {})
        data.update({
            str(field): str(value)
            for field, value in mapping.items()
        })

    def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(
            str(member) for member in members
        )

    def srem(self, key, *members):
        if key in self.sets:
            self.sets[key].difference_update(
                str(member) for member in members
            )

            if not self.sets[key]:
                del self.sets[key]

    def zadd(self, key, mapping):
        self.ranks.setdefault(key, {}).update({
            str(member): float(score)
            for member, score in mapping.items()
        })

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.sets.pop(key, None)
            self.ranks.pop(key, None)

    @property
    def keys(self):
        return set(self.hashes) | set(self.sets) | set(self.ranks)

def buat_snapshot(store, tanggal_acuan):
    snapshot = Snapshot()

    statistik_antar = defaultdict(Counter)
    statistik_sukses = defaultdict(Counter)

    jumlah_paket = 0
    jumlah_tarif = 0
    jumlah_kendaraan = 0

    for paket in loader.read_paket(store):
        loader.load_paket(snapshot, paket)
        loader.load_resi_order(snapshot, paket)
        loader.load_lokasi_resi(snapshot, paket)

        loader.hitung_statistik_kurir(
            paket,
            statistik_antar,
            statistik_sukses,
        )

        jumlah_paket += 1

    loader.load_statistik_kurir(
        snapshot,
        statistik_antar,
        statistik_sukses,
    )

    loader.load_rank_kurir(
        snapshot,
        statistik_antar,
        statistik_sukses,
    )

    tarif_terpilih = {}

    for tarif in loader.read_tarif(store):
        jumlah_tarif += 1

        if not loader.tarif_aktif(tarif, tanggal_acuan):
            continue

        rute = (
            tarif["jenis_layanan"],
            tarif["wilayah_asal"]["kode_wilayah"],
            tarif["wilayah_tujuan"]["kode_wilayah"],
        )

        versi = (
            date.fromisoformat(tarif["berlaku_mulai"][:10]),
            tarif["id_tarif"],
        )

        sebelumnya = tarif_terpilih.get(rute)

        if sebelumnya is None or versi > sebelumnya[0]:
            tarif_terpilih[rute] = (versi, tarif)

    for _, tarif in tarif_terpilih.values():
        loader.load_tarif(snapshot, tarif)

    # Pool kendaraan tersedia.
    for kendaraan in loader.read_kendaraan(store):
        loader.load_kendaraan(snapshot, kendaraan)
        jumlah_kendaraan += 1

    print( f"Sumber: {jumlah_paket} Paket, \n {jumlah_tarif} Tarif, \n {jumlah_kendaraan} Kendaraan")

    if (jumlah_paket == 0 or jumlah_tarif == 0 or jumlah_kendaraan == 0):
        raise ValueError( "Ada collection sumber kosong. " "Periksa sumber sebelum melakukan sinkronisasi.")

    return snapshot

pola_key = {
    "paket:*",
    "order:*:resi",
    "lokasi:*:*",
    "tarif:*:*:*",
    "kurir:*:antar",
    "kurir:*:sukses",
    "rank:kurir:*",
    "pool:*:kendaraan_tersedia",
}

def sync(garnet, snapshot, dry_run=True):
    key_lama = set()

    for pola in pola_key:
        key_lama.update(garnet.scan_iter(match=pola, count=500))

    berubah = 0

    kelompok = (
        ("hash", snapshot.hashes),
        ("set", snapshot.sets),
        ("zset", snapshot.ranks),
    )

    for jenis, kumpulan in kelompok:
        for key, data_baru in kumpulan.items():
            tipe_lama = garnet.type(key)
            data_lama = None

            if tipe_lama == jenis:
                if jenis == "hash":
                    data_lama = garnet.hgetall(key)

                elif jenis == "set":
                    data_lama = garnet.smembers(key)

                else:
                    data_lama = dict(garnet.zrange(key, 0, -1, withscores=True))

            if data_lama == data_baru:
                continue

            berubah += 1

            if dry_run:
                continue

            # Ganti seluruh isi key agar anggota/field lama hilang.
            garnet.delete(key)

            if jenis == "hash":
                garnet.hset(key, mapping=data_baru)

            elif jenis == "set":
                garnet.sadd(key, *data_baru)

            else:
                garnet.zadd(key, mapping=data_baru)

    # Bersihkan key yang tidak lagi dihasilkan oleh RavenDB.
    key_usang = key_lama - snapshot.keys

    if not dry_run:
        daftar_usang = sorted(key_usang)

        for offset in range(0, len(daftar_usang), 500):
            garnet.delete(
                *daftar_usang[offset:offset + 500]
            )

    label = "Rencana" if dry_run else "Selesai"

    print(f"{label}: {berubah} key ditambah/diganti, \n {len(key_usang)} key dihapus.")

def main():
    store = loader.store
    garnet = loader.garnet

    try:
        store.initialize()
        garnet.ping()
        snapshot = buat_snapshot(store,tanggal_acuan=date(2026, 1, 1),)
        sync(garnet,snapshot,dry_run=True,)

    finally:
        store.close()
        garnet.close()


if __name__ == "__main__":
    main()