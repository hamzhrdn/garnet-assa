# Garnet ASSA

Konfigurasi Garnet lokal dan skrip Python untuk memuat data pengiriman dari RavenDB ke Garnet. Aplikasi mengakses Garnet melalui client Redis.

## Prasyarat

- Docker dengan Docker Compose v2. Pada Windows, jalankan Docker Desktop dalam mode Linux containers.
- Python 3 dan `pip` untuk menjalankan skrip di repository ini.
- Git untuk clone repository.
- Akses ke database RavenDB dengan collection `Paket`, `Tarif`, dan `Kendaraan` untuk memuat data. RavenDB tidak disediakan oleh `compose.yml` ini.

Periksa tool yang terpasang:

```sh
docker --version
docker compose version
python --version
```

## 1. Clone repository

```sh
git clone https://github.com/hamzhrdn/garnet-assa.git
cd <repository>
```

Jalankan perintah selanjutnya dari direktori yang berisi `compose.yml`.

## 2. Jalankan Garnet

```sh
docker compose up -d
docker compose ps
docker compose logs --tail=50 garnet
```

Compose menggunakan image Microsoft Garnet yang dikunci ke digest pada `compose.yml`. Saat pertama kali dijalankan, Docker perlu mengunduh image tersebut.

Garnet dapat diakses dari komputer lokal di `127.0.0.1:6379`. Konfigurasi ini tidak mengatur password, volume penyimpanan, atau persistence. Perlakukan datanya sebagai cache sementara yang perlu dimuat ulang ketika server dimulai ulang.

## 3. Siapkan environment Python

**Windows PowerShell:**

```powershell
create conda -n garnet-assa python==3.12
conda activate garnet-assa
python -m pip install -r requirements.txt
```

## 4. Konfigurasi koneksi

Edit `.env` sesuai environment lokal:

| Variabel | Keterangan |
| --- | --- |
| `GARNET_HOST` | Host Garnet; default `127.0.0.1`. |
| `GARNET_PORT` | Port Garnet; default `6379`. |
| `GARNET_PASSWORD` | Kosongkan untuk Compose bawaan. Variabel ini hanya mengatur client, bukan password server. |
| `RAVEN_URL` | URL server RavenDB yang dapat diakses dari komputer tempat skrip Python dijalankan. |
| `RAVEN_DATABASE` | Nama database RavenDB yang berisi data sumber. |
| `RAVEN_CERT_PEM` | Path file sertifikat PEM jika RavenDB memerlukan sertifikat; kosongkan jika tidak digunakan. Pada Windows, path dapat ditulis seperti `C:/certs/client.pem`. |

## 5. Uji koneksi Garnet

Perintah berikut hanya membutuhkan Garnet dan dependency Python, tanpa koneksi RavenDB:

```sh
python -c "import os, redis; from dotenv import load_dotenv; load_dotenv(); r = redis.Redis(host=os.getenv('GARNET_HOST', '127.0.0.1'), port=int(os.getenv('GARNET_PORT', '6379')), password=os.getenv('GARNET_PASSWORD') or None, socket_connect_timeout=5, socket_timeout=5); print('PING:', r.ping()); r.close()"
```

Hasil yang diharapkan: `PING: True`.

## 6. Muat data dari RavenDB

Setelah database sumber tersedia dan `.env` sudah diisi:

```sh
python load_garnet.py
```

Skrip membaca collection `Paket`, `Tarif`, dan `Kendaraan`, lalu mengisi data paket, daftar resi per order/lokasi, tarif, statistik dan ranking kurir, serta kendaraan tersedia. Struktur dokumen harus sesuai field yang diakses dalam `load_garnet.py`; repository ini tidak menyediakan seed data RavenDB.

Loader menulis ke Garnet, tetapi tidak membersihkan seluruh data lama.

## 7. Jalankan contoh query

```sh
python query_garnet.py
```

Skrip menampilkan status paket dalam order serta durasi query. ID order contoh adalah `OP00000000000018`; ubah `id_order` di `main()` sesuai data yang sudah dimuat. Hasil bisa kosong jika order tersebut tidak tersedia.

Walaupun query membaca Garnet saja, `RAVEN_URL` dan `RAVEN_DATABASE` tetap perlu diisi karena skrip membuat objek `DocumentStore` ketika dijalankan.

## Mengelola container

```sh
# Lihat log secara langsung (Ctrl+C untuk keluar)
docker compose logs -f garnet

# Hentikan container
docker compose stop

# Jalankan kembali container
docker compose start

# Hapus container dan network Compose
docker compose down
```

Setelah server dimulai ulang, muat kembali cache dari RavenDB bila diperlukan.

## Struktur repository

```text
.
├── compose.yml        # Service Garnet lokal
├── requirements.txt   # Dependency Python
├── .env.example       # Template konfigurasi tanpa kredensial
├── load_garnet.py     # Memuat data RavenDB ke Garnet
├── sync.py            # Membandingkan dan menyinkronkan cache
├── query_garnet.py    # Contoh query status paket per order
└── README.md
```


Aturan `.gitignore` tidak berlaku surut pada file yang sudah dilacak. Jika PDF atau file lokal lain masih muncul pada `git ls-files` dan tidak ingin dipublikasikan, keluarkan dari index dengan `git rm --cached <nama-file>` sebelum commit. Perintah ini mempertahankan file lokal; file yang pernah di-commit tetap ada dalam riwayat Git.
