import os
import redis

from dotenv import load_dotenv
from time import perf_counter
from ravendb import DocumentStore
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

load_dotenv()

garnet = redis.Redis(
    host=os.getenv("GARNET_HOST", "127.0.0.1"),
    port=int(os.getenv("GARNET_PORT", "6379")),
    password=os.getenv("GARNET_PASSWORD") or None,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=30,
)

store = DocumentStore(
    urls=[os.environ["RAVEN_URL"]],
    database=os.environ["RAVEN_DATABASE"],
)

#query 2
def query_2(garnet, store, id_order):
    from time import perf_counter

    mulai = perf_counter()
    daftar_resi = sorted(garnet.smembers(f"order:{id_order}:resi"))
    hasil = []

    for offset in range(0, len(daftar_resi), 500):
        batch = daftar_resi[offset:offset + 500]

        with garnet.pipeline(transaction=False) as pipeline:
            for resi in batch:
                pipeline.hgetall(f"paket:{resi}")
            daftar_cache = pipeline.execute()

        with store.open_session() as session:
            dokumen = session.load([f"paket/{resi}" for resi in batch], object_type=dict, ) or {}
            for resi, cache in zip(batch, daftar_cache):
                paket = dokumen.get(f"paket/{resi}")
                if paket is None:
                    raise ValueError(f"Order merujuk paket yang tidak ada: {resi}")
                if not {"urutan", "status", "waktu"}.issubset(cache):
                    raise ValueError(f"Cache paket {resi} tidak lengkap, jalankan sinkronisasi.")
                punya_event = int(cache["urutan"]) > 0
                hasil.append({
                    "id_order": id_order,
                    "no_resi": resi,
                    "nama_kontak_penerima":
                        paket["penerima"]["nama_kontak"],
                    "status_terkini":
                        cache["status"] if punya_event else None,
                    "waktu_event":
                        cache["waktu"] if punya_event else None,
                })
    durasi_ms = (perf_counter() - mulai) * 1000
    return hasil, durasi_ms

#query 5
def query_5(garnet, store, tahun=2025):
    mulai = perf_counter()
    total_antar = Counter()
    total_sukses = Counter()

    with garnet.pipeline(transaction=False) as pipeline:
        for bulan in range(1, 13):
            periode = f"{tahun:04d}{bulan:02d}"
            pipeline.hgetall(f"kurir:{periode}:antar")
            pipeline.hgetall(f"kurir:{periode}:sukses")
        statistik = pipeline.execute()
    for indeks in range(0, len(statistik), 2):
        antar = {
            id_kurir: int(jumlah) for id_kurir, jumlah in statistik[indeks].items()
        }
        sukses = {
            id_kurir: int(jumlah) for id_kurir, jumlah in statistik[indeks+1].items()
        }
        for id_kurir in antar.keys() | sukses.keys():
            if not( 0 <= sukses.get(id_kurir, 0) <= antar.get(id_kurir, 0)):
                raise ValueError(f"Statistik tidak sesuai untuk {id_kurir}, periode {tahun:04d}{indeks//2+1:02d}")
        total_antar.update(antar)
        total_sukses.update(sukses)
    daftar_kurir = sorted( id_kurir for id_kurir, jumlah in total_antar.items() if jumlah >= 10 )

    hasil = []

    for offset in range(0, len(daftar_kurir), 500):
        batch = daftar_kurir[offset:offset+500]
        document_ids = [f"petugas/{id_kurir}" for id_kurir in batch]
        with store.open_session() as session:
            dokumen = session.load(document_ids, object_type = dict) or {}
            for id_kurir in batch:
                petugas = dokumen.get(f"petugas/{id_kurir}")
                if petugas is None : continue
                berhasil = total_sukses[id_kurir]
                total = total_antar[id_kurir]
                persen = ((Decimal(berhasil) / Decimal(total)) * Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                hasil.append({
                    "id_petugas": id_kurir,
                    "nama": petugas["nama"],
                    "status_kerja": petugas["status_kerja"],
                    "berhasil": berhasil,
                    "gagal": total - berhasil,
                    "persen_berhasil": persen,
                })
    hasil.sort(
        key=lambda item: (
            -item["persen_berhasil"],
            -item["berhasil"],
            item["id_petugas"],
        )
    )
    durasi_ms = (perf_counter() - mulai) * 1000
    return hasil, durasi_ms

#query 12
def query_15(garnet, store, id_order, no_resi, kode_tujuan):
    with store.open_session() as session:
        session.advanced.use_optimistic_concurrecy = True
        session.advabced.max_number_of_request_per_session = 10000
        order = session.load(f"order-pengiriman/{id_order}", object_type = dict)
        if order is None:
            return []

#query 13
#query 14
#query 17
#query 18
#query 19

def main(): 
    try:
        store.initialize()
        print("Koneksi Garnet:", garnet.ping())

        #Test Query 2
        id_order = "OP00000000045640"
        hasil_q2, waktu_q2 = query_2(garnet, store,  id_order)
        print("\nHasil Test Query 2")
        print(f"Order ID : {id_order}")
        print(f"Output Garnet : ")
        for paket in hasil_q2:
            print(paket["no_resi"], paket["status_terkini"])
        print(f"Waktu Eksekusi Query 2 : {waktu_q2} ms" )

        #Test Query 5
        hasil_q5, waktu_q5 = query_5(garnet, store, 2025)
        print("\nHasil Test Query 5")
        print(f"Tahun : {2025}")
        print(f"Output Garnet : ")
        for petugas in hasil_q5[:10]:
            print(petugas)
        print(f"Waktu Eksekusi Query 2 : {waktu_q5} ms" )

    finally:
        garnet.close()

if __name__ == "__main__":
    main()
