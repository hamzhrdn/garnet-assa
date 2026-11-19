# Loader RavenDB ke Garnet

`load_garnet.py` mengikuti contoh RavenDB bagian 3 dan struktur Garnet bagian 5
di `Desain_Struktur_NoSQL_Kelompok6.pdf`. Sumber dibaca dari collection `Paket`,
`Tarif`, dan `Kendaraan` dengan pagination. RavenDB tidak diubah.

```powershell
python -m pip install -r requirements.txt
python load_garnet.py --dry-run
python load_garnet.py
```

Konfigurasi di `.env` di sebelah script: `RAVEN_URL`, `RAVEN_DATABASE`,
opsional `RAVEN_CERT_PEM`, `GARNET_HOST` (default `127.0.0.1`),
`GARNET_PORT` (default `6379`), dan `GARNET_PASSWORD`.
`RAVEN_TEST_DOCUMENT_ID` tidak digunakan karena seluruh collection dibaca.

Tanggal acuan tarif default `2026-01-01`, sesuai asumsi desain. Ubah dengan
`--as-of 2025-06-01`. Batas tanggal berlaku bersifat inklusif; akhir `null`
berarti tidak dibatasi. Jika beberapa tarif aktif memiliki rute/layanan sama,
dipilih `berlaku_mulai` terbaru, lalu ID terbesar secara leksikografis jika seri.
Tanggal ini hanya menyaring tarif; statistik memuat seluruh riwayat event.

Hasil pengisian:

| Key | Tipe | Sumber |
| --- | --- | --- |
| `paket:{resi}` | Hash | Status terkini, urutan maksimum event, waktu/lokasi/kurir terakhir |
| `order:{order}:resi` | Set | `Paket.order.id_order` |
| `lokasi:{lokasi}:{status}` | Set | Lokasi dan status terkini paket |
| `tarif:{layanan}:{asal}:{tujuan}` | Hash | Tarif aktif pada tanggal acuan |
| `kurir:{yyyymm}:antar` / `sukses` | Hash | Event DITERIMA + GAGAL_ANTAR / DITERIMA |
| `rank:kurir:{periode}` | Sorted set | Persentase sukses bulanan (`202505`) dan triwulanan (`2025Q2`) |
| `pool:{lokasi}:kendaraan_tersedia` | Set | Kendaraan TERSEDIA |

Referensi seperti `petugas/PT1` disimpan sebagai `PT1`. Field opsional hash
yang kosong disimpan sebagai string kosong. Ranking triwulan dihitung dari
total sukses / total upaya, bukan rata-rata persentase bulanan.

Hentikan penulisan aplikasi ke RavenDB/Garnet selama rebuild. Semua sumber
dibaca dan divalidasi ke memori sebelum Garnet diubah. Loader mengganti isi key
dan membersihkan key usang **dalam pola tabel di atas**, termasuk key lama yang
belum pernah dibuat oleh script ini. Key lain tetap dipertahankan; tidak ada
`FLUSHDB`. Collection kosong membatalkan penulisan untuk mencegah pembersihan
akibat salah konfigurasi sumber.

Rebuild bukan transaksi lintas key. Jika koneksi putus saat penulisan, hasil
bisa parsial; perbaiki koneksi dan jalankan ulang sebelum aplikasi dilanjutkan.
Pengulangan menghasilkan statistik yang sama tanpa penambahan counter ganda.
Ukuran halaman dan batch perintah diatur melalui `--batch-size 1000`; seluruh
snapshot turunan tetap disimpan di memori.

```powershell
python -m unittest test_load_garnet -v
```

Tes menggunakan data tiruan, tanpa akses database. Referensi API:
[RavenDB Python query](https://ravendb.net/docs/article-page/7.0/Python/client-api/session/querying/how-to-query),
[Garnet data structures](https://microsoft.github.io/garnet/docs/commands/data-structures),
[Garnet generic commands](https://microsoft.github.io/garnet/docs/commands/generic).
