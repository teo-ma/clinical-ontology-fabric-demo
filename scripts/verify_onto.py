#!/usr/bin/env python3
"""Verify the 4 ontology-advantage query patterns against the warehouse."""
import struct, subprocess
import pyodbc

TENANT = "cba42e7d-491a-4df4-ab87-517dc39e2d51"
SERVER = "puxkjsy2jh2e3k4hkf64hhrnke-afyztpzgs4ve3o6se2e4bilj6a.datawarehouse.fabric.microsoft.com"
DATABASE = "ClinicalOntoWarehouse"

tok = subprocess.check_output([
    "az","account","get-access-token","--resource","https://database.windows.net/",
    "--tenant",TENANT,"--query","accessToken","-o","tsv"]).decode().strip()
tok_bytes = tok.encode("utf-16-le")
tok_struct = struct.pack('<I', len(tok_bytes)) + tok_bytes
conn = pyodbc.connect(
    f"Driver={{ODBC Driver 18 for SQL Server}};Server={SERVER},1433;Database={DATABASE};Encrypt=yes;TrustServerCertificate=no;",
    attrs_before={1256: tok_struct})
conn.autocommit = True
cur = conn.cursor()

QUERIES = {
"1. Taxonomy rollup — all patients with ANY Cardiovascular Disease (CVD subtree)": """
SELECT DISTINCT p.patient_id, p.patient_name, co.condition_name
FROM diagnoses d
JOIN condition_closure cc ON cc.descendant_code = d.condition_code
JOIN condition_ontology co ON co.condition_code = d.condition_code
JOIN patients p ON p.patient_id = d.patient_id
WHERE cc.ancestor_code = 'CVD'
ORDER BY p.patient_id;
""",

"2. Guideline gap — Type 2 Diabetes patients NOT on any recommended antidiabetic class": """
SELECT DISTINCT p.patient_id, p.patient_name
FROM diagnoses d
JOIN patients p ON p.patient_id = d.patient_id
WHERE d.condition_code = 'DM2'
AND NOT EXISTS (
    SELECT 1
    FROM prescriptions rx
    JOIN medication_ontology m ON m.medication_code = rx.medication_code
    JOIN drug_class_closure dcc ON dcc.descendant_code = m.class_code
    JOIN treatment_guideline g ON g.recommended_class_code = dcc.ancestor_code
    WHERE rx.patient_id = p.patient_id AND g.condition_code = 'DM2'
)
ORDER BY p.patient_id;
""",

"3. Interaction detection — patients co-prescribed two interacting medications": """
SELECT DISTINCT p.patient_id, p.patient_name,
       ma.medication_name AS med_a, mb.medication_name AS med_b, di.severity
FROM prescriptions rxa
JOIN prescriptions rxb ON rxa.patient_id = rxb.patient_id
JOIN drug_interaction di
     ON (di.med_code_a = rxa.medication_code AND di.med_code_b = rxb.medication_code)
JOIN medication_ontology ma ON ma.medication_code = rxa.medication_code
JOIN medication_ontology mb ON mb.medication_code = rxb.medication_code
JOIN patients p ON p.patient_id = rxa.patient_id
ORDER BY p.patient_id;
""",

"4. Referral network — referral volume by source/target specialty": """
SELECT s1.specialty_name AS from_specialty, s2.specialty_name AS to_specialty, COUNT(*) AS referrals
FROM referrals r
JOIN providers p1 ON p1.provider_id = r.from_provider_id
JOIN providers p2 ON p2.provider_id = r.to_provider_id
JOIN specialty_ontology s1 ON s1.specialty_code = p1.specialty_code
JOIN specialty_ontology s2 ON s2.specialty_code = p2.specialty_code
GROUP BY s1.specialty_name, s2.specialty_name
ORDER BY referrals DESC;
""",
}

for title, sql in QUERIES.items():
    print("="*80)
    print(title)
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    print("  cols:", cols)
    print(f"  rows: {len(rows)}")
    for r in rows[:8]:
        print("   ", tuple(r))

cur.close(); conn.close()
print("VERIFY DONE")
