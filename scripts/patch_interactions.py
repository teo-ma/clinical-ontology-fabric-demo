#!/usr/bin/env python3
"""Inject deliberate interacting co-prescriptions so the interaction-detection
ontology query returns meaningful results."""
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

# pick 4 patients, grab one encounter each, add an interacting med pair
cur.execute("""
SELECT patient_id, MIN(encounter_id) AS eid
FROM encounters
GROUP BY patient_id
ORDER BY patient_id
""")
pe = {r[0]: r[1] for r in cur.fetchall()}
targets = list(pe.items())[:4]

pairs = [("WARFAR","APIXAB"),   # High - dual anticoagulation
         ("WARFAR","FENOFI"),   # High - bleeding risk
         ("FUROSE","LISINO"),   # Moderate
         ("EMPAGL","FUROSE")]   # Moderate

cur.execute("SELECT ISNULL(MAX(CAST(SUBSTRING(rx_id,3,10) AS INT)),0) FROM prescriptions")
start = cur.fetchone()[0]
rows = []
seq = start
for (pid, eid), (ma, mb) in zip(targets, pairs):
    for mcode in (ma, mb):
        seq += 1
        rows.append((f"RX{seq:05d}", eid, pid, mcode, "2025-06-01", "10 mg", "Active"))

cur.fast_executemany = True
cur.executemany("INSERT INTO prescriptions VALUES (?,?,?,?,?,?,?)", rows)
print(f"Inserted {len(rows)} interacting prescriptions for patients: {[t[0] for t in targets]}")

# verify interaction query now returns rows
cur.execute("""
SELECT DISTINCT p.patient_id, p.patient_name,
       ma.medication_name AS med_a, mb.medication_name AS med_b, di.severity
FROM prescriptions rxa
JOIN prescriptions rxb ON rxa.patient_id = rxb.patient_id
JOIN drug_interaction di
     ON (di.med_code_a = rxa.medication_code AND di.med_code_b = rxb.medication_code)
JOIN medication_ontology ma ON ma.medication_code = rxa.medication_code
JOIN medication_ontology mb ON mb.medication_code = rxb.medication_code
JOIN patients p ON p.patient_id = rxa.patient_id
ORDER BY p.patient_id
""")
res = cur.fetchall()
print(f"Interaction query now returns {len(res)} rows:")
for r in res:
    print("  ", tuple(r))

cur.close(); conn.close()
print("PATCH DONE")
