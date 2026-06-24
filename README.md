# Clinical Ontology Demo on Microsoft Fabric

A clinical-analytics demo that shows **why an ontology (semantic knowledge model) beats flat SQL**
on a Microsoft Fabric Warehouse, wired into a Fabric **Data Agent** so you can ask questions in
natural language and have the agent reason over disease/drug taxonomies, treatment guidelines,
drug-interaction graphs and a referral network.

---

## 1. Business background

Healthcare data is intrinsically **hierarchical and graph-shaped**:

- A disease like *Essential Hypertension* is a kind of *Hypertension*, which is a kind of
  *Cardiovascular Disease*. Clinicians ask questions at **any level of that hierarchy**
  ("show me all cardiovascular patients"), but raw transactional data only stores leaf-level codes.
- Medications belong to **drug classes** (Lisinopril → ACE Inhibitor → Antihypertensive), and
  clinical guidelines are written in terms of **classes**, not individual drugs.
- Drugs **interact** with one another — a graph relationship, not a column.
- Care flows through a **referral network** between provider specialties.

With flat SQL you must hand-enumerate every leaf code, hard-code class membership, and write
brittle self-joins. An **ontology** captures these IS-A taxonomies and relationships once, so an
AI agent can answer **semantic, multi-hop questions** automatically.

This demo makes those advantages concrete and measurable.

---

## 2. Data

The dataset is generated deterministically (`random.seed(20260624)`) and loaded into a Fabric
Warehouse. It contains **17 tables** split into ontology/knowledge tables and fact tables.

### Ontology & knowledge tables

| Table | Rows | Purpose |
|---|---|---|
| `condition_ontology` | 27 | Disease IS-A taxonomy (`parent_code`) |
| `condition_closure` | 62 | Transitive closure of the disease taxonomy `(ancestor, descendant, depth)` |
| `drug_class` | 20 | Drug-class taxonomy (`parent_class_code`) |
| `drug_class_closure` | 35 | Transitive closure of the drug-class taxonomy |
| `medication_ontology` | 21 | Medication → drug class mapping |
| `treatment_guideline` | 20 | Recommended drug class per condition |
| `drug_interaction` | 9 | Drug–drug interaction graph (severity, description) |
| `specialty_ontology` | 6 | Provider specialty taxonomy |
| `lab_test_ontology` | 10 | Lab test catalog with normal ranges |

### Fact tables

| Table | Rows | Purpose |
|---|---|---|
| `patients` | 60 | Patient demographics |
| `providers` | 12 | Providers (specialty, facility) |
| `facilities` | 4 | Care facilities |
| `encounters` | 234 | Clinical encounters |
| `diagnoses` | 435 | Diagnoses per encounter (→ `condition_ontology`) |
| `prescriptions` | 102 | Prescriptions per encounter (→ `medication_ontology`) |
| `lab_results` | 400 | Lab results per encounter (→ `lab_test_ontology`) |
| `referrals` | 24 | Provider referral network |

The **closure tables** are the key trick: an IS-A taxonomy is pre-expanded so that any ancestor
query returns all descendants in a single join — no recursion, no code enumeration.

---

## 3. Ontology configuration

The knowledge model is described in [`ontology/clinical_ontology.yaml`](ontology/clinical_ontology.yaml):
entities, hierarchical taxonomies (with their closure tables), relationships (including
`INTERACTS_WITH`, `RECOMMENDED_TREATMENT`, `REFERRED`), and the four **inference patterns** the
ontology unlocks.

The same semantics are pushed into a Fabric **Data Agent** by
[`scripts/build_data_agent.py`](scripts/build_data_agent.py), which configures:

- a **data-warehouse datasource** over all 17 tables with per-table descriptions,
- **AI instructions** telling the agent to always exploit the ontology (use `condition_closure`
  for disease roll-ups, `treatment_guideline` for gaps, `drug_interaction` for co-prescriptions,
  `referrals` + `specialty_ontology` for care pathways),
- **few-shot examples** (Chinese) pairing natural-language questions with ontology-aware SQL.

> Implementation note: the Data Agent `updateDefinition` must reuse the agent's **own** default
> `data_agent.json` / `stage_config` `$schema` values (fetch them right after creating the agent);
> reusing templates from a different workspace's agent causes an opaque HTTP 500.

---

## 4. The four ontology-advantage patterns

`scripts/verify_onto.py` runs the four queries that are hard or impossible in naive flat SQL:

1. **Taxonomy roll-up** — every patient with *any* cardiovascular disease, by joining
   `diagnoses → condition_closure (ancestor='CVD')`. No leaf-code enumeration.
2. **Guideline gap** — Type-2-Diabetes patients **not** on any guideline-recommended antidiabetic
   *class*, via `treatment_guideline` + `drug_class_closure`.
3. **Interaction detection** — patients co-prescribed two **interacting** medications, surfacing
   severity from the `drug_interaction` graph.
4. **Referral network** — referral volume between provider **specialties**.

Verified sample output:

```
1. CVD roll-up ........... 63 rows (auto-includes HTN, CAD, HF, AF subtypes)
2. DM2 guideline gap ..... P0021, P0041
3. Interaction detection . 5 rows (e.g. Apixaban + Warfarin = High)
4. Referral network ...... GP→Endocrinology 9, GP→Cardiology 7, GP→Pulmonology 6, GP→Nephrology 2
```

---

## 5. Running the demo

### Prerequisites

- A Microsoft Fabric workspace on an F-SKU capacity, with a **Warehouse**.
- Azure CLI (`az login`), the **ODBC Driver 18 for SQL Server**, and Python with `pyodbc`.
- Update the `TENANT`, `SERVER`, `DATABASE` and workspace/warehouse IDs at the top of each script
  to match your environment.

### Steps

```bash
# 1. Generate & load the 17-table ontology dataset
python3 scripts/load_clinical_onto.py

# 2. Inject a few interacting co-prescriptions (pattern #3 demo data)
python3 scripts/patch_interactions.py

# 3. Verify the four ontology-advantage queries
python3 scripts/verify_onto.py

# 4. Build the ontology-aware Fabric Data Agent
python3 scripts/build_data_agent.py
```

### Ask the Data Agent

Open the `ClinicalOntologyAgent` Data Agent in Fabric, publish it, and ask (the few-shots are
in Chinese, but it answers in the user's language):

- 列出所有心血管疾病患者（含子类型） — *list all cardiovascular patients incl. subtypes*
- 哪些 2 型糖尿病患者没按指南用降糖药？ — *which T2D patients miss guideline antidiabetics?*
- 找出同时服用相互作用药物的患者 — *find patients on interacting drugs*
- 统计各专科之间的转诊量 — *referral volume by specialty*

---

## Repository layout

```
ontology/clinical_ontology.yaml   Knowledge model (entities, taxonomies, relationships, inference)
scripts/load_clinical_onto.py     Generate + load the 17-table dataset
scripts/patch_interactions.py     Add interacting co-prescriptions for the interaction demo
scripts/verify_onto.py            Run the 4 ontology-advantage queries
scripts/build_data_agent.py       Configure the ontology-aware Fabric Data Agent
```

> The scripts contain environment-specific identifiers (tenant, warehouse SQL endpoint, workspace
> GUIDs) from the demo environment — replace them with your own before running.
