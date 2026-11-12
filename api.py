import io
import os
from typing import List
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import pandas as pd

from extractor import extrage_text_din_pdf, analizeaza_text_factura

app = FastAPI(title="FacturiML SaaS API")


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
    Moneda: str = "RON"


class ExportPayload(BaseModel):
    invoices: List[FacturaRow]
    lang: str = "ro"


@app.get("/", response_class=HTMLResponse)
def afiseaza_dashboard():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/extract")
async def extrage_facturi_incarcate(files: List[UploadFile] = File(...)):
    rezultate = []
    for fisier in files:
        if fisier.filename.lower().endswith(".pdf"):
            continut_bytes = await fisier.read()
            pdf_in_ram = io.BytesIO(continut_bytes)
            text = extrage_text_din_pdf(pdf_in_ram)
            date = analizeaza_text_factura(text, fisier.filename)
            rezultate.append(date)
    return {"results": rezultate}


@app.get("/api/demo-invoices")
def incarca_facturi_locale():
    rezultate = []
    folder = "invoices"
    if os.path.exists(folder):
        for nume in sorted(os.listdir(folder)):
            if nume.lower().endswith(".pdf"):
                cale = os.path.join(folder, nume)
                text = extrage_text_din_pdf(cale)
                rezultate.append(analizeaza_text_factura(text, nume))
    return {"results": rezultate}


@app.post("/api/export-excel")
def exporta_excel_personalizat(payload: ExportPayload):
    date_tabel = [rand.model_dump() for rand in payload.invoices]
    df = pd.DataFrame(date_tabel)

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
            "Total_Plata": "Grand_Total",
            "Moneda": "Currency"
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
