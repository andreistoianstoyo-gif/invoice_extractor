import os
import io
from typing import List
import pandas as pd
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# Importăm funcțiile din extractorul tău
from extractor import extrage_text_din_pdf, analizeaza_text_factura

app = FastAPI(title="FacturiML SaaS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Modelul de date (Pydantic) care validează tabelul trimis din browser pentru export
class FacturaRow(BaseModel):
    Fisier: str
    Furnizor: str
    Client: str
    CUI: str
    Numar_Factura: str
    Data_Factura: str
    Subtotal: str
    TVA_VAT: str
    Total_Plata: str

class ExportPayload(BaseModel):
    invoices: List[FacturaRow]
    lang: str = "ro"


# 2. Ruta principală "/" care afișează site-ul când intri pe http://127.0.0.1:8000
@app.get("/", response_class=HTMLResponse)
def afiseaza_site():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


# 3. Extracție în RAM (100% privată pentru fiecare client în parte)
@app.post("/api/extract")
async def extrage_facturi_client(files: List[UploadFile] = File(...)):
    rezultate_client = []

    for fisier in files:
        if fisier.filename.lower().endswith(".pdf"):
            # Citim PDF-ul direct în memoria RAM (fără să îl salvăm pe disc)
            continut_bytes = await fisier.read()
            pdf_in_ram = io.BytesIO(continut_bytes)

            # pdfplumber știe să citească direct din obiectul RAM!
            text = extrage_text_din_pdf(pdf_in_ram)
            date_factura = analizeaza_text_factura(text, fisier.filename)
            rezultate_client.append(date_factura)

    return {"results": rezultate_client}


# 4. Generarea Excel-ului în RAM (păstrează și editările făcute de client pe site!)
@app.post("/api/export-excel")
@app.post("/api/export-excel")
def exporta_excel_personalizat(payload: ExportPayload):
    date_tabel = [rand.model_dump() for rand in payload.invoices]
    df = pd.DataFrame(date_tabel)

    # Dacă utilizatorul are comutatorul pe EN, traducem și coloanele și valorile "Negasit" din Excel
    if payload.lang == "en" and not df.empty:
        df = df.replace("Negasit", "Not Found")
        df = df.rename(columns={
            "Fisier": "File",
            "Furnizor": "Vendor",
            "Client": "Client",
            "CUI": "Tax_ID_VAT",
            "Numar_Factura": "Invoice_No",
            "Data_Factura": "Invoice_Date",
            "Subtotal": "Subtotal",
            "TVA_VAT": "VAT_Tax",
            "Total_Plata": "Grand_Total"
        })

    nume_foaie = "Extracted Invoices" if payload.lang == "en" else "Facturi Extrase"
    excel_in_ram = io.BytesIO()
    with pd.ExcelWriter(excel_in_ram, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=nume_foaie)
        foaie = writer.sheets[nume_foaie]
        for coloana in foaie.columns:
            lungime_max = max(len(str(celula.value or "")) for celula in coloana)
            litera = coloana[0].column_letter
            foaie.column_dimensions[litera].width = lungime_max + 4

    excel_in_ram.seek(0)
    return StreamingResponse(
        excel_in_ram,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=extracted_invoices.xlsx"}
    )


# 5. Rută opțională pentru tine (încarcă cele 8 facturi de test din folderul local 'invoices')
@app.get("/api/demo-invoices")
def incarca_demo():
    rezultate = []
    if os.path.exists("invoices"):
        for fisier in sorted(os.listdir("invoices")):
            if fisier.lower().endswith(".pdf"):
                cale = os.path.join("invoices", fisier)
                text = extrage_text_din_pdf(cale)
                rezultate.append(analizeaza_text_factura(text, fisier))
    return {"results": rezultate}
