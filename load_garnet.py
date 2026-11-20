from dotenv import load_dotenv
from ravendb import DocumentStore
from datetime import date, datetime
from collections import defaultdict, Counter
from time import perf_counter

import redis
import os
import json

load_dotenv()

#koneksi garnet
garnet = redis.Redis(
    host=os.getenv("GARNET_HOST", "127.0.0.1"),
    port=int(os.getenv("GARNET_PORT", "6379")),
    password=os.getenv("GARNET_PASSWORD") or None,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
)

#koneksi ravendb
store = DocumentStore(
    urls=[os.environ["RAVEN_URL"]],
    database=os.environ["RAVEN_DATABASE"],
)
certificate = os.getenv("RAVEN_CERT_PEM", "").strip()
if certificate:
    store.certificate_pem_path = certificate

#get data paket dari ravendb
def read_paket(store, batch_size = 1000, limit = None):
    offset = 0
    while limit is None or offset < limit:
        jumlah = batch_size
        if limit is not None:
            jumlah = min(batch_size, limit - offset)
        with store.open_session() as session:
            documents = list(
                session.advanced.raw_query(
                    "from 'Paket' order by id()",
                    object_type = dict
                ).skip(offset).take(jumlah)
            )
        if not documents:
            break
        yield from documents
        offset += len(documents)
        if len(documents) < jumlah:
            break

#write data paket ke garnet
def load_paket(garnet, paket):
    events = paket.get("events") or []
    event_terakhir = max(events, key=lambda event: int(event["urutan_event"]), default={} )
    status = (paket.get("status_terkini") or event_terakhir.get("status_pengiriman"))
    if not status:
        raise ValueError(f"Status paket {paket['no_resi']} tidak tersedia")
    id_lokasi = paket.get("id_lokasi_terkini", event_terakhir.get("id_lokasi"),)
    id_kurir = event_terakhir.get("id_kurir")

    id_lokasi = id_lokasi.rsplit("/", 1)[-1] if id_lokasi else ""
    id_kurir = id_kurir.rsplit("/", 1)[-1] if id_kurir else ""

    key = f"paket:{paket['no_resi']}"
    garnet.hset(
        key,
        mapping = {
            "status": status,
            "urutan": int(event_terakhir.get("urutan_event", 0)),
            "waktu": event_terakhir.get("waktu_event") or "",
            "id_lokasi": id_lokasi,
            "id_kurir": id_kurir,
        }        
    )
    return key

#write data resi 1 order
def load_resi_order(garnet, paket):
    referensi_order = paket['order']['id_order']
    id_order = referensi_order.rsplit("/", 1)[-1]
    key = f"order:{id_order}:resi"
    garnet.sadd(key, paket['no_resi'])
    return key

#write lokasi resi
def load_lokasi_resi(garnet, paket):
    id_lokasi = paket.get("id_lokasi_terkini")
    status = paket.get("status_terkini")

    if not id_lokasi:
        return None

    if not status:
        raise ValueError(f"Status paket {paket['no_resi']} tidak tersedia")

    id_lokasi = id_lokasi.rsplit("/", 1)[-1]
    key = f"lokasi:{id_lokasi}:{status}"
    garnet.sadd(key, paket['no_resi'])
    return key

#get data tarif dari ravendb
def read_tarif(store, batch_size = 1000):
    offset = 0
    while True:
        with store.open_session() as session:
            documents = list(
                session.advanced.raw_query(
                    "from 'Tarif' order by id()",
                    object_type = dict
                ).skip(offset).take(batch_size)
            )
        yield from documents
        offset += len(documents)
        if len(documents) < batch_size:
            break

#cek tarif aktif
def tarif_aktif(tarif, tanggal):
    mulai = date.fromisoformat(tarif["berlaku_mulai"][:10])
    sampai = tarif.get("berlaku_sampai")
    if sampai: 
        sampai = date.fromisoformat(sampai[:10])
    return (mulai <= tanggal and (sampai is None or tanggal <= sampai))

#write data ke garnet:
def load_tarif(garnet, tarif):
    layanan = tarif["jenis_layanan"]
    asal = tarif["wilayah_asal"]["kode_wilayah"]
    tujuan = tarif["wilayah_tujuan"]["kode_wilayah"]

    key = f"tarif:{layanan}:{asal}:{tujuan}"

    garnet.hset(
        key,
        mapping={
            "id_tarif" : tarif["id_tarif"].rsplit("/", 1)[-1],
            "harga_per_kg" : tarif["harga_per_kg"],
            "estimasi_waktu" : tarif["estimasi_waktu"],
        },
    )

    return key

#statistik kurir
def hitung_statistik_kurir(paket, statistik_antar, statistik_sukses):
    for event in paket.get("events") or []:
        status = event["status_pengiriman"]

        if status not in ("DITERIMA", "GAGAL_ANTAR"):
            continue

        referensi_kurir = event.get("id_kurir")

        if not referensi_kurir:
            raise ValueError(
                f"Event {status} pada paket "
                f"{paket['no_resi']} tidak memiliki id_kurir"
            )

        id_kurir = referensi_kurir.rsplit("/", 1)[-1]

        waktu = datetime.fromisoformat(event["waktu_event"])
        bulan = waktu.strftime("%Y%m")

        statistik_antar[bulan][id_kurir] += 1

        if status == "DITERIMA":
            statistik_sukses[bulan][id_kurir] += 1

#write statistik kurir
def load_statistik_kurir(garnet, statistik_antar, statistik_sukses):
    for bulan, jumlah_antar in statistik_antar.items():
        key_antar = f"kurir:{bulan}:antar"
        key_sukses = f"kurir:{bulan}:sukses"
        # Kurir tanpa keberhasilan tetap memiliki nilai sukses 0.
        jumlah_sukses = {
            id_kurir: statistik_sukses[bulan][id_kurir]
            for id_kurir in jumlah_antar
        }
        # Ganti isi bulan ini agar tidak meninggalkan field kurir lama.
        garnet.delete(key_antar, key_sukses)
        garnet.hset(key_antar, mapping=dict(jumlah_antar))
        garnet.hset(key_sukses, mapping=jumlah_sukses)

#write rank kurir
def load_rank_kurir(garnet, statistik_antar, statistik_sukses):
    antar_periode = defaultdict(Counter)
    sukses_periode = defaultdict(Counter)
    for bulan, jumlah_antar in statistik_antar.items():
        #kuartal
        tahun = bulan[:4]
        nomor_bulan = int(bulan[4:6])
        kuartal = (nomor_bulan - 1) // 3 + 1
        periode = f"{tahun}Q{kuartal}"
        antar_periode[periode].update(jumlah_antar)
        sukses_periode[periode].update(statistik_sukses.get(bulan, {}))
    for periode, jumlah_antar in antar_periode.items():
        skor = {}
        for id_kurir, total_antar in jumlah_antar.items():
            if total_antar <= 0:
                continue
            total_sukses = sukses_periode[periode][id_kurir]
            skor[id_kurir] = (total_sukses / total_antar * 100)

        key = f"rank:kurir:{periode}"
        # hapus ranking lama agar kurir yang sudah tidak ada ikut hilang.
        garnet.delete(key)
        if skor:
            garnet.zadd(key, mapping=skor)

#get data kendaraan
def read_kendaraan(store, batch_size=1000):
    offset = 0

    while True:
        with store.open_session() as session:
            documents = list(
                session.advanced.raw_query(
                    "from 'Kendaraan' order by id()",
                    object_type=dict,
                ).skip(offset).take(batch_size)
            )

        yield from documents

        if len(documents) < batch_size:
            break

        offset += len(documents)

#write data kendaraan
def load_kendaraan(garnet, kendaraan):
    id_lokasi = kendaraan["id_lokasi_basis"]

    if not id_lokasi:
        raise ValueError(f"Lokasi basis kendaraan {kendaraan['no_polisi']} kosong")

    id_lokasi = id_lokasi.rsplit("/", 1)[-1]
    key = f"pool:{id_lokasi}:kendaraan_tersedia"
    no_polisi = kendaraan["no_polisi"]

    if kendaraan["status_kendaraan"] == "TERSEDIA":
        garnet.sadd(key, no_polisi)
        return key

    garnet.srem(key, no_polisi)
    return None

def main():
    try:
        store.initialize()
        garnet.ping()
        statistik_antar = defaultdict(Counter)
        statistik_sukses = defaultdict(Counter)
        total_paket = 0

        #handle data paket
        start_load_paket = perf_counter()
        for paket in read_paket(store):
            load_paket(garnet, paket)
            load_resi_order(garnet, paket)
            load_lokasi_resi(garnet, paket)
            hitung_statistik_kurir(paket, statistik_antar, statistik_sukses, )
            total_paket += 1

        end_load_paket = perf_counter() - start_load_paket 
        print(f"waktu load data paket : {end_load_paket} s, total data paket : {total_paket}")

        #handle statistik kurir
        start_load_statistik_kurir = perf_counter()
        load_statistik_kurir(garnet,statistik_antar,statistik_sukses,)
        end_load_statistik_kurir = perf_counter() - start_load_statistik_kurir 
        print(f"waktu load data statistik : {end_load_statistik_kurir} s")

        #handle rank kurir
        start_load_rank_kurir = perf_counter()
        load_rank_kurir(garnet,statistik_antar,statistik_sukses,)
        end_load_rank_kurir = perf_counter() - start_load_rank_kurir 
        print(f"waktu load rank statistik : {end_load_rank_kurir} s")

        #load data tarif
        start_load_tarif = perf_counter()
        tanggal_acuan = date(2026, 1, 1)
        tarif_terpilih = {}

        for tarif in read_tarif(store):
            if not tarif_aktif(tarif, tanggal_acuan):
                continue
            rute = (
                tarif["jenis_layanan"],
                tarif["wilayah_asal"]["kode_wilayah"],
                tarif["wilayah_tujuan"]["kode_wilayah"],
            )
            versi = (date.fromisoformat(tarif["berlaku_mulai"][:10]), tarif["id_tarif"], )
            sebelumnya = tarif_terpilih.get(rute)
            if sebelumnya is None or versi > sebelumnya[0]:
                tarif_terpilih[rute] = (versi, tarif)
        end_load_tarif = perf_counter() - start_load_tarif
        print(
            f"\nSelesai: {len(tarif_terpilih)} tarif aktif untuk tanggal {tanggal_acuan} dimuat."
            f"\nWaktu load data {end_load_tarif} s"
        )

        #load data kendaraan pada pool
        total_kendaraan = 0
        total_tersedia = 0
        contoh_pool = None
        start_load_kendaraan = perf_counter()
        for kendaraan in read_kendaraan(store):
            key_pool = load_kendaraan(garnet, kendaraan)
            total_kendaraan += 1
            if key_pool:
                total_tersedia += 1
                if contoh_pool is None:
                    contoh_pool = key_pool
        print(f"\nJumlah Kendaraan diperiksa: {total_kendaraan}")
        print(f"Jumlah Kendaraan tersedia: {total_tersedia}")
        end_load_kendaraan = perf_counter() - start_load_kendaraan
        print(f"Waktu load Data kendaraan {end_load_kendaraan} s")
            
    finally:
        store.close()
        garnet.close()

if __name__ == "__main__":
    main()