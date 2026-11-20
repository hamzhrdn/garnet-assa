import os

import redis
from dotenv import load_dotenv
from time import perf_counter
from ravendb import DocumentStore

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
def query_2(garnet, id_order):
    mulai = perf_counter()
    daftar_resi = sorted(
        garnet.smembers(f"order:{id_order}:resi")
    )
    with garnet.pipeline(transaction=False) as pipeline:
        for resi in daftar_resi:
            pipeline.hgetall(f"paket:{resi}")
        daftar_paket = pipeline.execute()
    hasil = []
    for resi, paket in zip(daftar_resi, daftar_paket):
        if not paket or "status" not in paket:
            raise ValueError(f"Data Garnet tidak lengkap untuk paket {resi}")
        hasil.append({"no_resi": resi, "status": paket["status"], })
    durasi_ms = (perf_counter() - mulai) * 1000
    return hasil, durasi_ms

def main(): 
    try:
        print("Koneksi:", garnet.ping())

        #Test Query 2
        id_order = "OP00000000000018"
        hasil_garnet, waktu_garnet = query_2(garnet, id_order)

        print("Hasil Test Query 2")
        print(f"Order ID : {id_order}")
        print(f"Output Garnet : ")
        for paket in hasil_garnet:
            print(paket["no_resi"], paket["status"])
        print(f"Waktu Eksekusi Query 2 : {waktu_garnet} ms" )

        #Test Query 5
    finally:
        garnet.close()

if __name__ == "__main__":
    main()