from __future__ import annotations

import hashlib
import json
import tempfile
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.import_label_events import build_import  # noqa: E402
from scripts.prepare_labeling import _canonical, build_sheets  # noqa: E402


class WebLabelingTests(unittest.TestCase):
    def test_current_sheet_is_blind_and_bound_to_the_snapshot(self) -> None:
        snapshot = ROOT / "data" / "snapshots" / "20261007-e704e952"
        labels = ROOT / "eval" / "labels"
        sheets = build_sheets(snapshot, labels)
        self.assertEqual(sheets["snapshotId"], "20261007-e704e952")
        self.assertEqual((len(sheets["topics"]), len(sheets["pairs"]), len(sheets["claims"])), (120, 50, 32))
        self.assertEqual(sheets["sheetHash"], hashlib.sha256(_canonical({k:v for k,v in sheets.items() if k != "sheetHash"}).encode()).hexdigest())
        forbidden = {"predictedCategory", "predictedGeo", "predictedSameCluster", "supported", "citationCorrect", "label", "labeler", "labelMethod"}
        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(child) for child in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(child) for child in value)) if value else set()
            return set()
        self.assertFalse(forbidden & keys(sheets))

    def test_import_keeps_history_and_maps_latest_jury_judgments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sid = "snapshot-test"
            labels_dir, snapshot_dir = root / "labels", root / "snapshot"
            labels_dir.mkdir(); snapshot_dir.mkdir()
            articles = [
                {"articleId":"art-1","dataOrigin":"real","title":"Titular 1","outlet":"Medio 1","domain":"medio1.test","url":"https://medio1.test/1","publishedAt":None,"detectedAt":None},
                {"articleId":"art-2","dataOrigin":"real","title":"Titular 2","outlet":"Medio 2","domain":"medio2.test","url":"https://medio2.test/2","publishedAt":None,"detectedAt":None},
            ]
            articles_bytes = "".join(json.dumps(row, ensure_ascii=False)+"\n" for row in articles).encode()
            (snapshot_dir / "articles.jsonl").write_bytes(articles_bytes)
            articles_hash = hashlib.sha256(articles_bytes).hexdigest()
            (snapshot_dir / "manifest.json").write_text(json.dumps({"snapshotId":sid,"files":{"articles.jsonl":{"sha256":articles_hash}}}), encoding="utf-8")
            samples = {
                "cls_sample": [{"id":"art-1","articleId":"art-1","stratum":"uniforme"}],
                "pairs_sample": [{"id":"pair-1","a":"art-1","b":"art-2","stratum":"control"}],
                "claims_review": [{"id":"topic-1:c1","topicId":"topic-1","claimId":"c1","text":"afirmación","citations":[]}],
            }
            sample_hashes = {}
            for name, rows in samples.items():
                content = "".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows).encode()
                path = labels_dir / f"{name}.{sid}.jsonl"
                path.write_bytes(content)
                sample_hashes[path.name] = hashlib.sha256(content).hexdigest()
            (labels_dir / f"sheets.{sid}.meta.json").write_text(json.dumps({
                "snapshotId":sid,"articlesSha256":articles_hash,"method":"identical_evidence_rebind",
                "outputFilesSha256":sample_hashes,
            }), encoding="utf-8")
            sheet = build_sheets(snapshot_dir, labels_dir)
            sheets_path = root / "hojas.json"
            sheets_path.write_text(json.dumps(sheet), encoding="utf-8")
            session, other_session = str(uuid.uuid4()), str(uuid.uuid4())
            def event(label_type: str, item: str, value: str, created: str, role: str = "juror", signer: str = "Jurado", session_id: str = session) -> dict:
                return {"id":str(uuid.uuid4()),"snapshotId":sid,"sheetHash":sheet["sheetHash"],"type":label_type,"itemId":item,
                        "value":value,"comment":"revisado","role":role,"sessionId":session_id,"labeler":signer,
                        "labelMethod":"human","createdAt":created}
            events_juror = [
                event("topic","art-1","no_se","2026-10-08T10:00:00Z"),
                event("pair","pair-1","no","2026-10-08T10:01:00Z"),
            ]
            events_reviewer = [
                event("pair","pair-1","si","2026-10-08T10:02:00Z","reviewer","Revisora",other_session),
                event("claim","topic-1:c1","cita_incorrecta","2026-10-08T10:03:00Z","reviewer","Revisora",other_session),
            ]
            exports = []
            for name, events in (("juror",events_juror),("reviewer",events_reviewer)):
                export = root / f"{name}.json"
                export.write_text(json.dumps({"version":1,"snapshotId":sid,"sheetHash":sheet["sheetHash"],"labels":events}), encoding="utf-8")
                exports.append(export)
            files, report = build_import(exports, snapshot_dir, labels_dir, sheets_path)
            self.assertEqual(report["events"], 4)
            self.assertEqual(report["excludedNoSe"]["topic"], 1)
            self.assertEqual(report["itemsWithConflictingValues"], 1)
            pair_row = [json.loads(line) for line in files[f"pairs_labels.{sid}.jsonl"].decode().splitlines()]
            self.assertEqual(len(pair_row), 1)
            self.assertIs(pair_row[0]["sameEvent"], True)
            self.assertEqual(pair_row[0]["role"], "reviewer")
            claim_row = [json.loads(line) for line in files[f"claims_labels.{sid}.jsonl"].decode().splitlines()]
            self.assertIs(claim_row[0]["supported"], False)
            self.assertIs(claim_row[0]["citationCorrect"], False)
            events = [json.loads(line) for line in files[f"label_events.{sid}.jsonl"].decode().splitlines()]
            self.assertEqual(len(events), 4)
            self.assertEqual({event["role"] for event in events}, {"juror", "reviewer"})

    def test_import_rejects_a_sheet_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sid = "snapshot-test"
            labels_dir, snapshot_dir = root / "labels", root / "snapshot"
            labels_dir.mkdir(); snapshot_dir.mkdir()
            (snapshot_dir / "manifest.json").write_text(json.dumps({"snapshotId":sid,"files":{"articles.jsonl":{"sha256":"a"*64}}}), encoding="utf-8")
            for name in ("cls_sample", "pairs_sample", "claims_review"):
                (labels_dir / f"{name}.{sid}.jsonl").write_text("", encoding="utf-8")
            sheet = {"version":1,"snapshotId":sid,"topics":[],"pairs":[],"claims":[]}
            sheet["sheetHash"] = hashlib.sha256(_canonical(sheet).encode()).hexdigest()
            sheets_path = root / "hojas.json"; sheets_path.write_text(json.dumps(sheet), encoding="utf-8")
            export = root / "export.json"
            export.write_text(json.dumps({"version":1,"snapshotId":sid,"sheetHash":"0"*64,"labels":[]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no corresponde"):
                build_import(export, snapshot_dir, labels_dir, sheets_path)


if __name__ == "__main__":
    unittest.main()
