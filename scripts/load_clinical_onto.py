#!/usr/bin/env python3
"""Generate a rich ontology-centric clinical dataset and load into Fabric Warehouse."""
import struct, subprocess, random, datetime, sys
import pyodbc

random.seed(20260624)

TENANT = "cba42e7d-491a-4df4-ab87-517dc39e2d51"
SERVER = "puxkjsy2jh2e3k4hkf64hhrnke-afyztpzgs4ve3o6se2e4bilj6a.datawarehouse.fabric.microsoft.com"
DATABASE = "ClinicalOntoWarehouse"

# ---------------------------------------------------------------------------
# 1. ONTOLOGY DEFINITIONS
# ---------------------------------------------------------------------------
# condition taxonomy: code -> (name, parent, category)
CONDITIONS = {
    "CVD":    ("Cardiovascular Disease", None,  "chapter"),
    "HTN":    ("Hypertension", "CVD", "group"),
    "HTN1":   ("Essential Hypertension", "HTN", "leaf"),
    "HTN2":   ("Secondary Hypertension", "HTN", "leaf"),
    "CAD":    ("Coronary Artery Disease", "CVD", "group"),
    "MI":     ("Myocardial Infarction", "CAD", "leaf"),
    "ANGINA": ("Angina Pectoris", "CAD", "leaf"),
    "HF":     ("Heart Failure", "CVD", "group"),
    "HFREF":  ("HF with Reduced EF", "HF", "leaf"),
    "HFPEF":  ("HF with Preserved EF", "HF", "leaf"),
    "AF":     ("Atrial Fibrillation", "CVD", "leaf"),
    "ENDO":   ("Endocrine & Metabolic Disease", None, "chapter"),
    "DM":     ("Diabetes Mellitus", "ENDO", "group"),
    "DM1":    ("Type 1 Diabetes", "DM", "leaf"),
    "DM2":    ("Type 2 Diabetes", "DM", "leaf"),
    "DLP":    ("Dyslipidemia", "ENDO", "leaf"),
    "OBES":   ("Obesity", "ENDO", "leaf"),
    "THY":    ("Thyroid Disorder", "ENDO", "group"),
    "HYPOTHY":("Hypothyroidism", "THY", "leaf"),
    "HYPERTHY":("Hyperthyroidism", "THY", "leaf"),
    "RESP":   ("Respiratory Disease", None, "chapter"),
    "COPD":   ("Chronic Obstructive Pulmonary Disease", "RESP", "leaf"),
    "ASTHMA": ("Asthma", "RESP", "leaf"),
    "RENAL":  ("Renal Disease", None, "chapter"),
    "CKD":    ("Chronic Kidney Disease", "RENAL", "group"),
    "CKD3":   ("CKD Stage 3", "CKD", "leaf"),
    "CKD4":   ("CKD Stage 4", "CKD", "leaf"),
}

# drug class taxonomy
DRUG_CLASSES = {
    "ANTIHTN": ("Antihypertensives", None),
    "ACEI":    ("ACE Inhibitors", "ANTIHTN"),
    "ARB":     ("Angiotensin Receptor Blockers", "ANTIHTN"),
    "BB":      ("Beta Blockers", "ANTIHTN"),
    "CCB":     ("Calcium Channel Blockers", "ANTIHTN"),
    "DIUR":    ("Diuretics", "ANTIHTN"),
    "ANTIDM":  ("Antidiabetics", None),
    "MET":     ("Biguanides", "ANTIDM"),
    "SU":      ("Sulfonylureas", "ANTIDM"),
    "SGLT2":   ("SGLT2 Inhibitors", "ANTIDM"),
    "INSULIN": ("Insulin", "ANTIDM"),
    "LIPID":   ("Lipid Lowering Agents", None),
    "STATIN":  ("Statins", "LIPID"),
    "FIBRATE": ("Fibrates", "LIPID"),
    "ANTICOAG":("Anticoagulants", None),
    "DOAC":    ("Direct Oral Anticoagulants", "ANTICOAG"),
    "VKA":     ("Vitamin K Antagonists", "ANTICOAG"),
    "RESPMED": ("Respiratory Medications", None),
    "BRONCHO": ("Bronchodilators", "RESPMED"),
    "ICS":     ("Inhaled Corticosteroids", "RESPMED"),
}

# medications: code -> (name, class_code)
MEDICATIONS = {
    "LISINO": ("Lisinopril", "ACEI"),
    "ENALAP": ("Enalapril", "ACEI"),
    "LOSART": ("Losartan", "ARB"),
    "VALSAR": ("Valsartan", "ARB"),
    "METOPR": ("Metoprolol", "BB"),
    "CARVED": ("Carvedilol", "BB"),
    "AMLODI": ("Amlodipine", "CCB"),
    "HCTZ":   ("Hydrochlorothiazide", "DIUR"),
    "FUROSE": ("Furosemide", "DIUR"),
    "METFOR": ("Metformin", "MET"),
    "GLIPIZ": ("Glipizide", "SU"),
    "EMPAGL": ("Empagliflozin", "SGLT2"),
    "GLARGI": ("Insulin Glargine", "INSULIN"),
    "ATORVA": ("Atorvastatin", "STATIN"),
    "ROSUVA": ("Rosuvastatin", "STATIN"),
    "FENOFI": ("Fenofibrate", "FIBRATE"),
    "APIXAB": ("Apixaban", "DOAC"),
    "RIVARO": ("Rivaroxaban", "DOAC"),
    "WARFAR": ("Warfarin", "VKA"),
    "SALBUT": ("Salbutamol", "BRONCHO"),
    "BUDESO": ("Budesonide", "ICS"),
}

# treatment guidelines: condition_code -> list of recommended class_code
GUIDELINES = {
    "HTN":  ["ACEI", "ARB", "CCB", "DIUR"],
    "HF":   ["ACEI", "BB", "DIUR"],
    "CAD":  ["STATIN", "BB"],
    "AF":   ["DOAC"],
    "DM2":  ["MET", "SGLT2"],
    "DM1":  ["INSULIN"],
    "DLP":  ["STATIN"],
    "CKD":  ["ACEI", "ARB"],
    "COPD": ["BRONCHO", "ICS"],
    "ASTHMA":["ICS", "BRONCHO"],
}

# drug-drug interactions: (med_a, med_b, severity, description)
INTERACTIONS = [
    ("WARFAR", "FENOFI", "High", "Fibrate potentiates warfarin, bleeding risk"),
    ("WARFAR", "ROSUVA", "Moderate", "Statin may increase INR"),
    ("APIXAB", "WARFAR", "High", "Concurrent anticoagulation contraindicated"),
    ("RIVARO", "WARFAR", "High", "Concurrent anticoagulation contraindicated"),
    ("FUROSE", "LISINO", "Moderate", "Diuretic + ACEI risk of hypotension/AKI"),
    ("FUROSE", "ENALAP", "Moderate", "Diuretic + ACEI risk of hypotension/AKI"),
    ("EMPAGL", "FUROSE", "Moderate", "SGLT2 + loop diuretic volume depletion"),
    ("METFOR", "FUROSE", "Moderate", "Risk of lactic acidosis with diuretic"),
    ("GLIPIZ", "METOPR", "Moderate", "Beta blocker may mask hypoglycemia"),
]

# specialty taxonomy
SPECIALTIES = {
    "MED":   ("Internal Medicine", None),
    "CARD":  ("Cardiology", "MED"),
    "ENDOCR":("Endocrinology", "MED"),
    "NEPH":  ("Nephrology", "MED"),
    "PULM":  ("Pulmonology", "MED"),
    "GP":    ("General Practice", None),
}

# lab tests: code -> (name, category, normal_low, normal_high, unit)
TESTS = {
    "LDL":     ("LDL Cholesterol", "LIPID", 0.0, 3.4, "mmol/L"),
    "HDL":     ("HDL Cholesterol", "LIPID", 1.0, 3.0, "mmol/L"),
    "TG":      ("Triglycerides", "LIPID", 0.0, 1.7, "mmol/L"),
    "HBA1C":   ("HbA1c", "GLUCOSE", 4.0, 6.0, "%"),
    "FBG":     ("Fasting Blood Glucose", "GLUCOSE", 3.9, 6.1, "mmol/L"),
    "CREAT":   ("Creatinine", "RENAL", 44.0, 106.0, "umol/L"),
    "EGFR":    ("eGFR", "RENAL", 90.0, 120.0, "mL/min"),
    "BNP":     ("BNP", "CARDIAC", 0.0, 100.0, "pg/mL"),
    "TROPON":  ("Troponin", "CARDIAC", 0.0, 0.04, "ng/mL"),
    "TSH":     ("TSH", "THYROID", 0.4, 4.0, "mIU/L"),
}

# ---------------------------------------------------------------------------
# 2. TRANSITIVE CLOSURE (ontology reasoning helper)
# ---------------------------------------------------------------------------
def build_closure(nodes):
    """nodes: code -> parent. Returns list of (ancestor, descendant, depth) incl self(0)."""
    parent = {c: p for c, p in nodes.items()}
    rows = []
    for code in parent:
        rows.append((code, code, 0))         # self
        anc = parent[code]
        depth = 1
        while anc is not None:
            rows.append((anc, code, depth))
            anc = parent.get(anc)
            depth += 1
    return rows

cond_parent = {c: v[1] for c, v in CONDITIONS.items()}
class_parent = {c: v[1] for c, v in DRUG_CLASSES.items()}
COND_CLOSURE = build_closure(cond_parent)
CLASS_CLOSURE = build_closure(class_parent)

# ---------------------------------------------------------------------------
# 3. FACT DATA GENERATION
# ---------------------------------------------------------------------------
CITIES = [("Seattle","West"),("Portland","West"),("Chicago","Midwest"),
          ("Boston","Northeast"),("Austin","South"),("Denver","West")]
FIRST = ["James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda",
         "William","Elizabeth","David","Barbara","Richard","Susan","Joseph","Jessica",
         "Thomas","Sarah","Charles","Karen","Chris","Nancy","Daniel","Lisa",
         "Matthew","Betty","Anthony","Margaret","Mark","Sandra"]
LAST = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
        "Rodriguez","Martinez","Hernandez","Lopez","Wilson","Anderson","Taylor","Moore"]

# facilities
FACILITIES = [
    ("F01","Northgate Medical Center","Seattle","West"),
    ("F02","Riverside Hospital","Chicago","Midwest"),
    ("F03","Harbor Clinic","Boston","Northeast"),
    ("F04","Summit Health","Denver","West"),
]

# providers
prov_specialties = ["CARD","CARD","ENDOCR","ENDOCR","NEPH","PULM","GP","GP","CARD","ENDOCR","GP","PULM"]
PROVIDERS = []
for i, sp in enumerate(prov_specialties, 1):
    pid = f"DR{i:02d}"
    fac = FACILITIES[(i-1) % 4][0]
    name = f"Dr. {random.choice(LAST)}"
    PROVIDERS.append((pid, name, sp, fac))

# patients
N_PATIENTS = 60
PATIENTS = []
for i in range(1, N_PATIENTS+1):
    pid = f"P{i:04d}"
    g = random.choice(["M","F"])
    by = random.randint(1945, 2000)
    bd = datetime.date(by, random.randint(1,12), random.randint(1,28))
    city, region = random.choice(CITIES)
    enr = datetime.date(2024, random.randint(1,12), random.randint(1,28))
    PATIENTS.append((pid, f"{random.choice(FIRST)} {random.choice(LAST)}", g, bd, city, region, enr))

LEAF_CONDITIONS = [c for c,v in CONDITIONS.items() if v[2]=="leaf"] + ["DLP","OBES","AF","COPD","ASTHMA","CKD3","CKD4"]
LEAF_CONDITIONS = list(dict.fromkeys(LEAF_CONDITIONS))

# Assign each patient a set of chronic conditions, encounters, dx, rx, labs
encounters, diagnoses, prescriptions, labs, referrals = [], [], [], [], []
enc_seq = dx_seq = rx_seq = lab_seq = ref_seq = 0

# map condition -> meds via guideline classes -> meds
class_to_meds = {}
for mcode, (mn, cc) in MEDICATIONS.items():
    class_to_meds.setdefault(cc, []).append(mcode)

def meds_for_condition(cond):
    classes = GUIDELINES.get(cond, [])
    meds = []
    for cl in classes:
        meds += class_to_meds.get(cl, [])
    return meds

for (pid, *_rest) in PATIENTS:
    n_cond = random.randint(1, 4)
    patient_conditions = random.sample(LEAF_CONDITIONS, n_cond)
    n_enc = random.randint(2, 6)
    enc_dates = sorted(datetime.date(2025, random.randint(1,12), random.randint(1,28)) for _ in range(n_enc))
    for ed in enc_dates:
        enc_seq += 1
        prov = random.choice(PROVIDERS)
        eid = f"E{enc_seq:05d}"
        etype = random.choice(["Outpatient","Inpatient","Emergency","Follow-up"])
        encounters.append((eid, pid, prov[0], prov[3], ed, etype))
        # diagnoses for this encounter (subset of patient conditions)
        for cond in random.sample(patient_conditions, random.randint(1, len(patient_conditions))):
            dx_seq += 1
            diagnoses.append((f"D{dx_seq:05d}", eid, pid, cond, ed, "Active"))
            # prescribe guideline meds sometimes (intentionally leave gaps for demo)
            if random.random() < 0.7:
                cand = meds_for_condition(cond)
                if cand:
                    mcode = random.choice(cand)
                    rx_seq += 1
                    prescriptions.append((f"RX{rx_seq:05d}", eid, pid, mcode, ed,
                                          f"{random.choice([5,10,20,25,40,50])} mg", "Active"))
            # labs relevant to condition
            test_pool = []
            if cond in ("DM1","DM2"): test_pool = ["HBA1C","FBG"]
            elif cond in ("DLP",): test_pool = ["LDL","HDL","TG"]
            elif cond in ("CKD3","CKD4"): test_pool = ["CREAT","EGFR"]
            elif cond in ("HFREF","HFPEF"): test_pool = ["BNP"]
            elif cond in ("MI",): test_pool = ["TROPON"]
            elif cond in ("HYPOTHY","HYPERTHY"): test_pool = ["TSH"]
            for tc in test_pool:
                tn, cat, lo, hi, unit = TESTS[tc]
                lab_seq += 1
                # generate value, ~40% abnormal
                if random.random() < 0.4:
                    val = round(hi * random.uniform(1.1, 1.8), 2)
                    flag = "High"
                else:
                    val = round(random.uniform(lo if lo>0 else hi*0.3, hi*0.95), 2)
                    flag = "Normal"
                labs.append((f"L{lab_seq:05d}", eid, pid, tc, val, unit, ed, flag))
        # referral (sometimes GP -> specialist)
        if prov[2] == "GP" and random.random() < 0.4 and patient_conditions:
            spec_provs = [p for p in PROVIDERS if p[2] in ("CARD","ENDOCR","NEPH","PULM")]
            tp = random.choice(spec_provs)
            ref_seq += 1
            referrals.append((f"REF{ref_seq:04d}", prov[0], tp[0], pid, ed,
                              random.choice(patient_conditions)))

print(f"Generated: patients={len(PATIENTS)} providers={len(PROVIDERS)} encounters={len(encounters)} "
      f"diagnoses={len(diagnoses)} prescriptions={len(prescriptions)} labs={len(labs)} referrals={len(referrals)}")
print(f"Ontology: conditions={len(CONDITIONS)} cond_closure={len(COND_CLOSURE)} drug_classes={len(DRUG_CLASSES)} "
      f"class_closure={len(CLASS_CLOSURE)} medications={len(MEDICATIONS)} interactions={len(INTERACTIONS)} "
      f"guidelines={sum(len(v) for v in GUIDELINES.values())}")

# ---------------------------------------------------------------------------
# 4. CONNECT
# ---------------------------------------------------------------------------
tok = subprocess.check_output([
    "az","account","get-access-token","--resource","https://database.windows.net/",
    "--tenant",TENANT,"--query","accessToken","-o","tsv"]).decode().strip()
tok_bytes = tok.encode("utf-16-le")
tok_struct = struct.pack('<I', len(tok_bytes)) + tok_bytes
conn_str = (f"Driver={{ODBC Driver 18 for SQL Server}};Server={SERVER},1433;"
            f"Database={DATABASE};Encrypt=yes;TrustServerCertificate=no;")
conn = pyodbc.connect(conn_str, attrs_before={1256: tok_struct})
conn.autocommit = True
cur = conn.cursor()
print("Connected to warehouse.")

# ---------------------------------------------------------------------------
# 5. DDL
# ---------------------------------------------------------------------------
DDL = [
    "condition_ontology", "DROP TABLE IF EXISTS condition_ontology",
    """CREATE TABLE condition_ontology(condition_code VARCHAR(10), condition_name VARCHAR(80),
        parent_code VARCHAR(10), category VARCHAR(20))""",
    "condition_closure", "DROP TABLE IF EXISTS condition_closure",
    """CREATE TABLE condition_closure(ancestor_code VARCHAR(10), descendant_code VARCHAR(10), depth INT)""",
    "drug_class", "DROP TABLE IF EXISTS drug_class",
    """CREATE TABLE drug_class(class_code VARCHAR(12), class_name VARCHAR(60), parent_class_code VARCHAR(12))""",
    "drug_class_closure", "DROP TABLE IF EXISTS drug_class_closure",
    """CREATE TABLE drug_class_closure(ancestor_code VARCHAR(12), descendant_code VARCHAR(12), depth INT)""",
    "medication_ontology", "DROP TABLE IF EXISTS medication_ontology",
    """CREATE TABLE medication_ontology(medication_code VARCHAR(10), medication_name VARCHAR(60), class_code VARCHAR(12))""",
    "treatment_guideline", "DROP TABLE IF EXISTS treatment_guideline",
    """CREATE TABLE treatment_guideline(condition_code VARCHAR(10), recommended_class_code VARCHAR(12))""",
    "drug_interaction", "DROP TABLE IF EXISTS drug_interaction",
    """CREATE TABLE drug_interaction(med_code_a VARCHAR(10), med_code_b VARCHAR(10), severity VARCHAR(12), description VARCHAR(120))""",
    "specialty_ontology", "DROP TABLE IF EXISTS specialty_ontology",
    """CREATE TABLE specialty_ontology(specialty_code VARCHAR(10), specialty_name VARCHAR(60), parent_code VARCHAR(10))""",
    "lab_test_ontology", "DROP TABLE IF EXISTS lab_test_ontology",
    """CREATE TABLE lab_test_ontology(test_code VARCHAR(10), test_name VARCHAR(60), category VARCHAR(20),
        normal_low FLOAT, normal_high FLOAT, unit VARCHAR(12))""",
    "facilities", "DROP TABLE IF EXISTS facilities",
    """CREATE TABLE facilities(facility_id VARCHAR(6), facility_name VARCHAR(60), city VARCHAR(30), region VARCHAR(20))""",
    "providers", "DROP TABLE IF EXISTS providers",
    """CREATE TABLE providers(provider_id VARCHAR(6), provider_name VARCHAR(60), specialty_code VARCHAR(10), facility_id VARCHAR(6))""",
    "patients", "DROP TABLE IF EXISTS patients",
    """CREATE TABLE patients(patient_id VARCHAR(8), patient_name VARCHAR(60), gender CHAR(1),
        birth_date DATE, city VARCHAR(30), region VARCHAR(20), enrolled_date DATE)""",
    "encounters", "DROP TABLE IF EXISTS encounters",
    """CREATE TABLE encounters(encounter_id VARCHAR(8), patient_id VARCHAR(8), provider_id VARCHAR(6),
        facility_id VARCHAR(6), encounter_date DATE, encounter_type VARCHAR(20))""",
    "diagnoses", "DROP TABLE IF EXISTS diagnoses",
    """CREATE TABLE diagnoses(diagnosis_id VARCHAR(8), encounter_id VARCHAR(8), patient_id VARCHAR(8),
        condition_code VARCHAR(10), diagnosis_date DATE, status VARCHAR(12))""",
    "prescriptions", "DROP TABLE IF EXISTS prescriptions",
    """CREATE TABLE prescriptions(rx_id VARCHAR(8), encounter_id VARCHAR(8), patient_id VARCHAR(8),
        medication_code VARCHAR(10), start_date DATE, dose VARCHAR(20), status VARCHAR(12))""",
    "lab_results", "DROP TABLE IF EXISTS lab_results",
    """CREATE TABLE lab_results(lab_id VARCHAR(8), encounter_id VARCHAR(8), patient_id VARCHAR(8),
        test_code VARCHAR(10), result_value FLOAT, unit VARCHAR(12), result_date DATE, abnormal_flag VARCHAR(10))""",
    "referrals", "DROP TABLE IF EXISTS referrals",
    """CREATE TABLE referrals(referral_id VARCHAR(8), from_provider_id VARCHAR(6), to_provider_id VARCHAR(6),
        patient_id VARCHAR(8), referral_date DATE, reason_condition_code VARCHAR(10))""",
]
i = 0
while i < len(DDL):
    label = DDL[i]; drop = DDL[i+1]; create = DDL[i+2]
    cur.execute(drop); cur.execute(create)
    print(f"  DDL ok: {label}")
    i += 3

# ---------------------------------------------------------------------------
# 6. INSERTS
# ---------------------------------------------------------------------------
def insert_many(sql, rows):
    if not rows: return
    cur.fast_executemany = True
    cur.executemany(sql, rows)

insert_many("INSERT INTO condition_ontology VALUES (?,?,?,?)",
            [(c, v[0], v[1], v[2]) for c, v in CONDITIONS.items()])
insert_many("INSERT INTO condition_closure VALUES (?,?,?)", COND_CLOSURE)
insert_many("INSERT INTO drug_class VALUES (?,?,?)",
            [(c, v[0], v[1]) for c, v in DRUG_CLASSES.items()])
insert_many("INSERT INTO drug_class_closure VALUES (?,?,?)", CLASS_CLOSURE)
insert_many("INSERT INTO medication_ontology VALUES (?,?,?)",
            [(c, v[0], v[1]) for c, v in MEDICATIONS.items()])
insert_many("INSERT INTO treatment_guideline VALUES (?,?)",
            [(cond, cl) for cond, cls in GUIDELINES.items() for cl in cls])
insert_many("INSERT INTO drug_interaction VALUES (?,?,?,?)", INTERACTIONS)
insert_many("INSERT INTO specialty_ontology VALUES (?,?,?)",
            [(c, v[0], v[1]) for c, v in SPECIALTIES.items()])
insert_many("INSERT INTO lab_test_ontology VALUES (?,?,?,?,?,?)",
            [(c, v[0], v[1], v[2], v[3], v[4]) for c, v in TESTS.items()])
insert_many("INSERT INTO facilities VALUES (?,?,?,?)", FACILITIES)
insert_many("INSERT INTO providers VALUES (?,?,?,?)", PROVIDERS)
insert_many("INSERT INTO patients VALUES (?,?,?,?,?,?,?)", PATIENTS)
insert_many("INSERT INTO encounters VALUES (?,?,?,?,?,?)", encounters)
insert_many("INSERT INTO diagnoses VALUES (?,?,?,?,?,?)", diagnoses)
insert_many("INSERT INTO prescriptions VALUES (?,?,?,?,?,?,?)", prescriptions)
insert_many("INSERT INTO lab_results VALUES (?,?,?,?,?,?,?,?)", labs)
insert_many("INSERT INTO referrals VALUES (?,?,?,?,?,?)", referrals)
print("All inserts done.")

# ---------------------------------------------------------------------------
# 7. VERIFY COUNTS
# ---------------------------------------------------------------------------
for t in ["condition_ontology","condition_closure","drug_class","drug_class_closure",
          "medication_ontology","treatment_guideline","drug_interaction","specialty_ontology",
          "lab_test_ontology","facilities","providers","patients","encounters","diagnoses",
          "prescriptions","lab_results","referrals"]:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t}: {cur.fetchone()[0]}")

cur.close(); conn.close()
print("DONE")
