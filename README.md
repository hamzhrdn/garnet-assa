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

Ganti URL berikut dengan URL repository GitHub kamu:

```sh
git clone https://github.com/<username>/<repository>.git
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
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Jika aktivasi virtual environment diblokir oleh PowerShell, gunakan executable Python-nya langsung, tanpa mengubah execution policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Gunakan `.\.venv\Scripts\python.exe` sebagai pengganti `python` pada perintah selanjutnya jika environment tidak diaktifkan.

**Linux / macOS:**

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Salin `.env.example` hanya pada setup awal agar konfigurasi `.env` yang sudah ada tidak tertimpa.

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

Nilai RavenDB di `.env.example` adalah contoh, bukan layanan yang otomatis dibuat. Sesuaikan dengan server dan database kamu. Sertifikat digunakan oleh `load_garnet.py` dan `sync.py`.

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

Tanggal acuan tarif saat ini ditetapkan ke **1 Januari 2026** di `load_garnet.py` dan `sync.py`. Ubah keduanya jika membutuhkan tanggal acuan lain.

Loader menulis ke Garnet, tetapi tidak membersihkan seluruh data lama. Untuk melihat perubahan yang diperlukan agar cache sesuai sumber, jalankan:

```sh
python sync.py
```

Secara default, `sync.py` memakai `dry_run=True`: membaca sumber dan cache, lalu menampilkan jumlah key yang akan ditambah/diganti dan dihapus tanpa menulis perubahan. Skrip menolak sinkronisasi jika salah satu collection sumber kosong.

Untuk menerapkan sinkronisasi, ubah argumen pemanggilan `sync()` di `main()` menjadi `dry_run=False`, lalu jalankan kembali. Mode ini mengganti key yang berbeda dan menghapus key usang sesuai pola pada `pola_key`; gunakan instance Garnet khusus proyek ini. Sinkronisasi berjalan sekali per eksekusi, bukan otomatis di latar belakang.

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

## Troubleshooting

| Masalah | Pemeriksaan |
| --- | --- |
| Docker tidak dapat terhubung ke daemon | Pastikan Docker Desktop / Docker Engine berjalan. |
| Port `6379` sudah digunakan | Hentikan layanan yang memakai port tersebut atau ubah mapping menjadi `127.0.0.1:6380:6379` di `compose.yml` dan isi `GARNET_PORT=6380` pada `.env`. |
| Koneksi Garnet ditolak | Periksa `docker compose ps`, log service, serta host dan port pada `.env`. |
| `KeyError: 'RAVEN_URL'` / `'RAVEN_DATABASE'` | Pastikan `.env` tersedia dan kedua variabel sudah diisi. |
| RavenDB menolak koneksi | Periksa URL, nama database, akses jaringan, serta path dan izin sertifikat jika diperlukan. |
| Query tidak mengembalikan paket | Jalankan loader dan pilih ID order yang ada pada data sumber. |
| Instalasi dependency gagal | Periksa pesan `pip`, versi Python, dan ketersediaan versi paket dalam `requirements.txt` pada package index yang digunakan. |

## Sebelum push ke GitHub

`.env`, virtual environment, cache Python, dan file sertifikat dikecualikan melalui `.gitignore`. Commit `.env.example` sebagai template konfigurasi; jangan isi template dengan kredensial asli.

Periksa isi perubahan sebelum commit:

```sh
git status --short
git diff
git diff --cached
git ls-files
```

Aturan `.gitignore` tidak berlaku surut pada file yang sudah dilacak. Jika PDF atau file lokal lain masih muncul pada `git ls-files` dan tidak ingin dipublikasikan, keluarkan dari index dengan `git rm --cached <nama-file>` sebelum commit. Perintah ini mempertahankan file lokal; file yang pernah di-commit tetap ada dalam riwayat Git.
