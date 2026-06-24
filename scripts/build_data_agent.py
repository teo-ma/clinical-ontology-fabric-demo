#!/usr/bin/env python3
import json, base64, subprocess, time, urllib.request, urllib.error, uuid
TENANT="cba42e7d-491a-4df4-ab87-517dc39e2d51"
NEW_WS="bf997101-9726-4d2a-bbd2-2689c0a169f0"
WH_ID="446c9531-cc9f-4675-8f91-05d55aba64ff"
WH_NAME="ClinicalOntoWarehouse"
AGENT_NAME="ClinicalOntologyAgent"
API="https://api.fabric.microsoft.com/v1"
tok=subprocess.check_output(["az","account","get-access-token","--resource","https://api.fabric.microsoft.com","--tenant",TENANT,"--query","accessToken","-o","tsv"]).decode().strip()
H={"Authorization":f"Bearer {tok}","Content-Type":"application/json"}
def req(method,url,body=None):
    data=json.dumps(body).encode() if body is not None else b""
    r=urllib.request.Request(url,data=data,headers=H,method=method)
    try:
        resp=urllib.request.urlopen(r); return resp.status,dict(resp.headers),resp.read()
    except urllib.error.HTTPError as e:
        return e.code,dict(e.headers),e.read()
def lro(method,url,body=None):
    st,hd,bd=req(method,url,body)
    if st in (200,201): return st,bd
    if st==202:
        loc=hd.get("Location") or hd.get("location")
        for _ in range(60):
            time.sleep(3); s2,h2,b2=req("GET",loc); j=json.loads(b2) if b2 else {}
            if j.get("status")=="Succeeded":
                s3,h3,b3=req("GET",loc+"/result"); return s3,b3
            if j.get("status")=="Failed": return 500,b2
        return 504,b"to"
    return st,bd
def b64(o): return base64.b64encode(json.dumps(o,ensure_ascii=False).encode()).decode()

# delete any existing agent with that name, then wait for name reclaim
_st,_h,_b=req("GET",f"{API}/workspaces/{NEW_WS}/items")
for it in json.loads(_b).get("value",[]):
    if it.get("displayName")==AGENT_NAME and it.get("type")=="DataAgent":
        req("DELETE",f"{API}/workspaces/{NEW_WS}/items/{it['id']}")
        print("deleted stale",it["id"])

# create fresh (retry name reclaim)
new_id=None
for _ in range(20):
    st,hd,bd=req("POST",f"{API}/workspaces/{NEW_WS}/items",{"displayName":AGENT_NAME,"type":"DataAgent"})
    if st in (200,201): new_id=json.loads(bd)["id"]; break
    if st==202:
        loc=hd.get("Location") or hd.get("location")
        for _ in range(40):
            time.sleep(3); s2,h2,b2=req("GET",loc); j=json.loads(b2) if b2 else {}
            if j.get("status")=="Succeeded":
                s3,h3,b3=req("GET",loc+"/result"); new_id=json.loads(b3)["id"]; break
        if new_id: break
    if st==409 and b"NotAvailableYet" in bd:
        print("name not available yet..."); time.sleep(15); continue
    print("create failed",st,bd.decode()); raise SystemExit(1)
print("agent id:",new_id)

# fetch the agent's OWN default parts to reuse exact $schema values
st,bd=lro("POST",f"{API}/workspaces/{NEW_WS}/items/{new_id}/getDefinition")
cur={p["path"]:p for p in json.loads(bd)["definition"]["parts"]}
data_agent=json.loads(base64.b64decode(cur["Files/Config/data_agent.json"]["payload"]).decode())
stage_schema=json.loads(base64.b64decode(cur["Files/Config/draft/stage_config.json"]["payload"]).decode())["$schema"]

TABLES={
 "condition_ontology":[("condition_code","varchar"),("condition_name","varchar"),("parent_code","varchar"),("category","varchar")],
 "condition_closure":[("ancestor_code","varchar"),("descendant_code","varchar"),("depth","int")],
 "drug_class":[("class_code","varchar"),("class_name","varchar"),("parent_class_code","varchar")],
 "drug_class_closure":[("ancestor_code","varchar"),("descendant_code","varchar"),("depth","int")],
 "medication_ontology":[("medication_code","varchar"),("medication_name","varchar"),("class_code","varchar")],
 "treatment_guideline":[("condition_code","varchar"),("recommended_class_code","varchar")],
 "drug_interaction":[("med_code_a","varchar"),("med_code_b","varchar"),("severity","varchar"),("description","varchar")],
 "specialty_ontology":[("specialty_code","varchar"),("specialty_name","varchar"),("parent_code","varchar")],
 "lab_test_ontology":[("test_code","varchar"),("test_name","varchar"),("category","varchar"),("normal_low","float"),("normal_high","float"),("unit","varchar")],
 "facilities":[("facility_id","varchar"),("facility_name","varchar"),("city","varchar"),("region","varchar")],
 "providers":[("provider_id","varchar"),("provider_name","varchar"),("specialty_code","varchar"),("facility_id","varchar")],
 "patients":[("patient_id","varchar"),("patient_name","varchar"),("gender","char"),("birth_date","date"),("city","varchar"),("region","varchar"),("enrolled_date","date")],
 "encounters":[("encounter_id","varchar"),("patient_id","varchar"),("provider_id","varchar"),("facility_id","varchar"),("encounter_date","date"),("encounter_type","varchar")],
 "diagnoses":[("diagnosis_id","varchar"),("encounter_id","varchar"),("patient_id","varchar"),("condition_code","varchar"),("diagnosis_date","date"),("status","varchar")],
 "prescriptions":[("rx_id","varchar"),("encounter_id","varchar"),("patient_id","varchar"),("medication_code","varchar"),("start_date","date"),("dose","varchar"),("status","varchar")],
 "lab_results":[("lab_id","varchar"),("encounter_id","varchar"),("patient_id","varchar"),("test_code","varchar"),("result_value","float"),("unit","varchar"),("result_date","date"),("abnormal_flag","varchar")],
 "referrals":[("referral_id","varchar"),("from_provider_id","varchar"),("to_provider_id","varchar"),("patient_id","varchar"),("referral_date","date"),("reason_condition_code","varchar")],
}
DESC={
 "condition_ontology":"Disease IS-A taxonomy. condition_code, condition_name, parent_code, category. CVD is Cardiovascular Disease, DM is Diabetes Mellitus.",
 "condition_closure":"Transitive closure of the condition taxonomy: ancestor_code, descendant_code, depth. Join diagnoses to descendant_code and filter ancestor_code to get all sub-conditions.",
 "drug_class":"Drug-class taxonomy with parent_class_code.",
 "drug_class_closure":"Transitive closure of the drug-class taxonomy.",
 "medication_ontology":"Medication to drug class mapping via class_code.",
 "treatment_guideline":"Guideline recommended drug class per condition. Use for guideline gap analysis.",
 "drug_interaction":"Drug-drug interaction pairs with severity and description.",
 "specialty_ontology":"Provider specialty taxonomy with parent_code.",
 "lab_test_ontology":"Lab test catalog with category and normal range.",
 "facilities":"Care facilities.",
 "providers":"Providers with specialty_code and facility_id.",
 "patients":"Patient demographics.",
 "encounters":"Clinical encounters linking patient, provider and facility.",
 "diagnoses":"Diagnoses per encounter. condition_code references condition_ontology.",
 "prescriptions":"Prescriptions per encounter. medication_code references medication_ontology.",
 "lab_results":"Lab results per encounter. test_code references lab_test_ontology.",
 "referrals":"Provider referral network from_provider_id to to_provider_id with reason_condition_code.",
}
def col(n,d): return {"id":None,"is_selected":True,"display_name":n,"type":"warehouse_tables.column","data_type":d,"description":None,"children":[]}
def tbl(n): return {"id":None,"is_selected":True,"display_name":n,"type":"warehouse_tables.table","description":DESC[n],"children":[col(c,d) for c,d in TABLES[n]]}

datasource={
 "$schema":"https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataSource/1.0.0/schema.json",
 "artifactId":WH_ID,"workspaceId":NEW_WS,
 "dataSourceInstructions":"Ontology-first clinical warehouse. To find patients with a broad disease category such as cardiovascular disease (CVD), diabetes (DM), endocrine (ENDO), respiratory (RESP) or renal (CKD), join diagnoses.condition_code to condition_closure.descendant_code and filter condition_closure.ancestor_code to the category code. Never enumerate leaf codes. Use medication_ontology with drug_class_closure for drug classes, treatment_guideline for guideline gaps, drug_interaction for interacting drugs, and referrals with specialty_ontology for care pathways.",
 "displayName":WH_NAME,"type":"data_warehouse",
 "userDescription":"Ontology-rich clinical warehouse with disease and drug-class taxonomies, transitive closure, treatment guidelines, drug-interaction graph and referral network.",
 "metadata":None,
 "elements":[{"id":None,"is_selected":True,"display_name":"dbo","type":"warehouse_tables.schema","description":None,"children":[tbl(t) for t in TABLES]}]
}

ai_instructions=("You are a clinical analytics agent over an ontology-rich Fabric Warehouse. Always exploit the ontology. "
 "For a disease category (Cardiovascular Disease CVD, Diabetes DM, Type 2 Diabetes DM2, Endocrine ENDO, Respiratory RESP, Renal CKD), "
 "join diagnoses to condition_closure on descendant_code and filter ancestor_code to the category code to auto-include all sub-conditions. "
 "Use medication_ontology and drug_class_closure for drug-class roll-ups. Use treatment_guideline to find guideline gaps "
 "(patients diagnosed but not prescribed the recommended drug class). Use drug_interaction to find patients co-prescribed interacting medications. "
 "Use referrals with specialty_ontology for referral and care-pathway analysis. Reply in the user's language.")
stage={"$schema":stage_schema,"aiInstructions":ai_instructions}

def fs(q,sql): return {"id":str(uuid.uuid4()),"question":q,"query":sql}
fewshots={"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataSource/fewShots/1.0.0/schema.json",
 "fewShots":[
  fs("列出所有患有心血管疾病的患者（含所有子类型）",
     "SELECT DISTINCT p.patient_id, p.patient_name, co.condition_name FROM diagnoses d JOIN condition_closure cc ON cc.descendant_code = d.condition_code JOIN condition_ontology co ON co.condition_code = d.condition_code JOIN patients p ON p.patient_id = d.patient_id WHERE cc.ancestor_code = 'CVD' ORDER BY p.patient_id;"),
  fs("哪些2型糖尿病患者没有按指南使用任何降糖药？",
     "SELECT DISTINCT p.patient_id, p.patient_name FROM diagnoses d JOIN patients p ON p.patient_id = d.patient_id WHERE d.condition_code = 'DM2' AND NOT EXISTS (SELECT 1 FROM prescriptions rx JOIN medication_ontology m ON m.medication_code = rx.medication_code JOIN drug_class_closure dcc ON dcc.descendant_code = m.class_code JOIN treatment_guideline g ON g.recommended_class_code = dcc.ancestor_code WHERE rx.patient_id = p.patient_id AND g.condition_code = 'DM2') ORDER BY p.patient_id;"),
  fs("找出同时服用相互作用药物的患者及严重程度",
     "SELECT DISTINCT p.patient_id, p.patient_name, ma.medication_name AS med_a, mb.medication_name AS med_b, di.severity FROM prescriptions rxa JOIN prescriptions rxb ON rxa.patient_id = rxb.patient_id JOIN drug_interaction di ON di.med_code_a = rxa.medication_code AND di.med_code_b = rxb.medication_code JOIN medication_ontology ma ON ma.medication_code = rxa.medication_code JOIN medication_ontology mb ON mb.medication_code = rxb.medication_code JOIN patients p ON p.patient_id = rxa.patient_id ORDER BY p.patient_id;"),
  fs("统计各专科之间的转诊量",
     "SELECT s1.specialty_name AS from_specialty, s2.specialty_name AS to_specialty, COUNT(*) AS referrals FROM referrals r JOIN providers p1 ON p1.provider_id = r.from_provider_id JOIN providers p2 ON p2.provider_id = r.to_provider_id JOIN specialty_ontology s1 ON s1.specialty_code = p1.specialty_code JOIN specialty_ontology s2 ON s2.specialty_code = p2.specialty_code GROUP BY s1.specialty_name, s2.specialty_name ORDER BY referrals DESC;"),
  fs("统计每个疾病大类下的患者数量",
     "SELECT root.condition_name AS category, COUNT(DISTINCT d.patient_id) AS patients FROM condition_ontology root JOIN condition_closure cc ON cc.ancestor_code = root.condition_code JOIN diagnoses d ON d.condition_code = cc.descendant_code WHERE root.category = 'chapter' GROUP BY root.condition_name ORDER BY patients DESC;"),
 ]}

ds_dir="Files/Config/draft/data-warehouse-ClinicalOntoWarehouse"
parts=[
 {"path":"Files/Config/data_agent.json","payload":b64(data_agent),"payloadType":"InlineBase64"},
 {"path":"Files/Config/draft/stage_config.json","payload":b64(stage),"payloadType":"InlineBase64"},
 {"path":f"{ds_dir}/datasource.json","payload":b64(datasource),"payloadType":"InlineBase64"},
 {"path":f"{ds_dir}/fewshots.json","payload":b64(fewshots),"payloadType":"InlineBase64"},
]
st,bd=lro("POST",f"{API}/workspaces/{NEW_WS}/items/{new_id}/updateDefinition",{"definition":{"parts":parts}})
print("updateDefinition:",st,(bd[:300].decode(errors='replace') if bd else ""))
st,bd=lro("POST",f"{API}/workspaces/{NEW_WS}/items/{new_id}/getDefinition")
got={p["path"]:p for p in json.loads(bd)["definition"]["parts"]}
print("parts:",list(got))
if f"{ds_dir}/datasource.json" in got:
    dsj=json.loads(base64.b64decode(got[f"{ds_dir}/datasource.json"]["payload"]).decode())
    fsj=json.loads(base64.b64decode(got[f"{ds_dir}/fewshots.json"]["payload"]).decode())
    print("datasource type:",dsj["type"],"tables:",len(dsj["elements"][0]["children"]),"fewshots:",len(fsj["fewShots"]))
print("AGENT_ID="+new_id)
