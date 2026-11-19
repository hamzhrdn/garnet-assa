import unittest
from datetime import date

from load_garnet import Snapshot, read_collection, write_snapshot


class MemoryGarnet:
    def __init__(self):
        self.data = {"setup:test": "keep", "lokasi:OLD:TIBA_DI_HUB": {"RS1"}}

    def scan_iter(self, match, count):
        from fnmatch import fnmatchcase
        return [key for key in self.data if fnmatchcase(key, match)]

    def pipeline(self, transaction):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self):
        pass

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    def hset(self, key, mapping):
        self.data.setdefault(key, {}).update(mapping)

    def zadd(self, key, mapping):
        self.hset(key, mapping)

    def sadd(self, key, *members):
        self.data.setdefault(key, set()).update(members)


def package(resi="RS1"):
    return {
        "no_resi": resi, "order": {"id_order": "order-pengiriman/OP1"},
        "status_terkini": "DITERIMA", "id_lokasi_terkini": None,
        "events": [
            {"urutan_event": 9, "waktu_event": "2025-05-02T14:30:00",
             "status_pengiriman": "DITERIMA", "id_kurir": "petugas/PT1"},
            {"urutan_event": 2, "waktu_event": "2025-04-01T10:00:00",
             "status_pengiriman": "GAGAL_ANTAR", "id_kurir": "petugas/PT1"},
        ],
    }


class LoaderTests(unittest.TestCase):
    def test_package_and_weighted_quarter(self):
        snapshot = Snapshot(date(2026, 1, 1))
        snapshot.add_package(package())
        other = package("RS2")
        other["events"] = [other["events"][0]]
        snapshot.add_package(other)
        snapshot.finish()
        self.assertEqual(snapshot.hashes["paket:RS1"]["urutan"], 9)
        self.assertEqual(snapshot.hashes["paket:RS1"]["id_lokasi"], "")
        self.assertEqual(snapshot.sets["order:OP1:resi"], {"RS1", "RS2"})
        self.assertEqual(snapshot.hashes["kurir:202504:sukses"], {"PT1": 0})
        self.assertAlmostEqual(snapshot.ranks["rank:kurir:2025Q2"]["PT1"], 200 / 3)

    def test_active_tariff_and_latest_version(self):
        snapshot = Snapshot(date(2026, 1, 1))
        tariff = {"id_tarif": "tarif/TF1", "jenis_layanan": "REG",
                  "wilayah_asal": {"kode_wilayah": "01"},
                  "wilayah_tujuan": {"kode_wilayah": "02"},
                  "harga_per_kg": 9000, "estimasi_waktu": "2-3 hari",
                  "berlaku_mulai": "2025-01-01", "berlaku_sampai": "2026-01-01"}
        snapshot.add_tariff(tariff)
        snapshot.add_tariff(dict(tariff, id_tarif="TF2", berlaku_mulai="2025-12-01"))
        snapshot.add_tariff(dict(tariff, id_tarif="TF3", berlaku_mulai="2026-01-02", berlaku_sampai=None))
        snapshot.add_tariff(dict(tariff, id_tarif="TF4", berlaku_sampai="2025-12-31"))
        self.assertEqual(snapshot.hashes["tarif:REG:01:02"]["id_tarif"], "TF2")

    def test_rebuild_removes_stale_members_and_preserves_other_keys(self):
        snapshot = Snapshot(date(2026, 1, 1))
        snapshot.add_package(package())
        snapshot.add_vehicle({"no_polisi": "D123ABC", "status_kendaraan": "TERSEDIA",
                              "id_lokasi_basis": "lokasi/PO1"})
        snapshot.finish()
        client = MemoryGarnet()
        client.data["order:OP1:resi"] = {"STALE"}
        write_snapshot(client, snapshot, 2)
        first = repr(client.data)
        write_snapshot(client, snapshot, 2)
        self.assertEqual(repr(client.data), first)
        self.assertNotIn("lokasi:OLD:TIBA_DI_HUB", client.data)
        self.assertEqual(client.data["setup:test"], "keep")
        self.assertEqual(client.data["order:OP1:resi"], {"RS1"})
        self.assertEqual(client.data["pool:PO1:kendaraan_tersedia"], {"D123ABC"})

    def test_invalid_events_fail(self):
        doc = package()
        doc["events"][1]["urutan_event"] = 9
        with self.assertRaises(ValueError):
            Snapshot(date(2026, 1, 1)).add_package(doc)

    def test_paging_reads_all_pages(self):
        class Session:
            def __enter__(self):
                self.advanced = self
                return self

            def __exit__(self, *args):
                pass

            def raw_query(self, query, object_type):
                return self

            def skip(self, offset):
                self.offset = offset
                return self

            def take(self, size):
                return list(range(5))[self.offset:self.offset + size]

        class Store:
            def open_session(self):
                return Session()

        self.assertEqual(list(read_collection(Store(), "Paket", 2)), list(range(5)))


if __name__ == "__main__":
    unittest.main()
