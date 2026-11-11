import os
import re
import pdfplumber
import spacy
import pandas as pd

# 1. Încărcăm modelul general RO și modelul nostru ML Custom antrenat
nlp_general = spacy.load("ro_core_news_sm")
nlp_custom = spacy.load("model_facturi_ml") if os.path.exists("model_facturi_ml") else None

# 2. Dicționar extins (Română + Engleză + Coloana Client)
SINONIME_CAMPURI = {
    "Furnizor": [
        r"(?:furnizor|firma|distribuitor|vanzator|prestator|emitent|unitate\s+emitenta|vendor|billed\s+by|company|from)\s*[:\-]\s*([^\n\r\|]+)",
    ],
    "Client": [
        r"(?:client|cumparator|beneficiar|catre\s+abonat|catre|billed\s+to|bill\s+to|customer|to)\s*[:\-]\s*([^\n\r\(\|]+)",
    ],
    "CUI": [
        r"(?:c\.?u\.?i\.?|c\.?i\.?f\.?|cod\s+(?:inregistrare\s+)?fiscala?|cod\s+unic\s+de\s+inregistrare|vat\s*(?:id|no|number|reg)?|tax\s*id|reg\.?\s*no)\s*[:\-]?\s*(RO\s*\d+|\d+|[A-Z]{2}\s*\d+)",
    ],
    "Numar_Factura": [
        r"seria\s*[:\-]?\s*([A-Za-z0-9]+\s+nr\.?\s*[:\-]?\s*[A-Za-z0-9\-]+)",
        r"(?:serie\s+si\s+numar|factura\s+fiscala\s+nr|factura\s+nr|nr\.\s*factura|numar\s+factura|doc\.\s*nr|invoice\s*(?:no|number|id|#)|factura)\s*[:\-\.\s]+\s*([A-Za-z0-9\-\/]+)",
    ],
    "Data_Factura": [
        r"(?:data\s+emiterii|data\s+facturarii|data\s+document|data|invoice\s+date|date)\s*[:\-]?\s*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{4}|\d{4}[\.\/\-]\d{1,2}[\.\/\-]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})",
    ],
    "Subtotal": [
        r"(?:subtotal|sub-total|total\s+fara\s+tva|baza\s+impozabila|valoare\s+fara\s+tva|net\s+amount)\s*[:\-\=]?\s*(?:RON|LEI|EUR|USD|\$|€|£)?\s*([\d\.,]+)",
    ],
    "TVA_VAT": [
        r"(?<!fara\s)(?:valoare\s+tva|tva|vat|sales\s+tax|tax)(?:\s*\(?[\d\.,]+%\)?)?\s*[:\-\=\.]+\s*(?:RON|LEI|EUR|USD|\$|€|£)?\s*([\d\.,]+)(?![\d\.,]|\s*%)",
    ],
    "Total_Plata": [
        r"(?:total\s+de\s+plata|total\s+general|total\s+factura|suma\s+de\s+plata|valoare\s+totala|de\s+achitat|total\s+due|amount\s+due|grand\s+total|balance\s+due|total\s+amount)\s*[:\-\=]?\s*(?:RON|LEI|EUR|USD|\$|€|£)?\s*([\d\.,]+)",
        r"(?<!sub)(?<!fara\s)\btotal\s*[:\-\=]\s*(?:RON|LEI|EUR|USD|\$|€|£)?\s*([\d\.,]+)",
    ]
}

FORME_JURIDICE = r"\b(?:S\.?R\.?L\.?|S\.?A\.?|P\.?F\.?A\.?|I\.?I\.?|INC\.?|LLC|LTD\.?|CORP\.?|GMBH)\b"


def extrage_text_din_pdf(cale_pdf):
    text_complet = ""
    with pdfplumber.open(cale_pdf) as pdf:
        for pagina in pdf.pages:
            text_pagina = pagina.extract_text()
            if text_pagina:
                text_complet += text_pagina + "\n"
    return text_complet


def transforma_in_numar(text_suma):
    if text_suma == "Negasit":
        return None
    curat = text_suma.strip()
    if "," in curat and (curat.rfind(",") > curat.rfind(".")):
        curat = curat.replace(".", "").replace(",", ".")
    else:
        curat = curat.replace(",", "")
    try:
        return float(curat)
    except ValueError:
        return None


def completeaza_sume_contabile(date_extrase):
    sub = transforma_in_numar(date_extrase["Subtotal"])
    tva = transforma_in_numar(date_extrase["TVA_VAT"])
    tot = transforma_in_numar(date_extrase["Total_Plata"])

    if sub is None and tot is not None and tva is not None:
        date_extrase["Subtotal"] = f"{tot - tva:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif tva is None and tot is not None and sub is not None:
        date_extrase["TVA_VAT"] = f"{tot - sub:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif sub is None and tva is None and tot is not None:
        date_extrase["Subtotal"] = date_extrase["Total_Plata"]
        date_extrase["TVA_VAT"] = "0,00"

    return date_extrase


def analizeaza_text_factura(text, nume_fisier):
    date_extrase = {
        "Fisier": nume_fisier,
        "Furnizor": "Negasit",
        "Client": "Negasit",
        "CUI": "Negasit",
        "Numar_Factura": "Negasit",
        "Data_Factura": "Negasit",
        "Subtotal": "Negasit",
        "TVA_VAT": "Negasit",
        "Total_Plata": "Negasit"
    }

    # PASUL 1: Extracție prin reguli (Regex)
    for camp_standard, lista_sabloane in SINONIME_CAMPURI.items():
        for sablon in lista_sabloane:
            potrivire = re.search(sablon, text, re.IGNORECASE)
            if potrivire:
                date_extrase[camp_standard] = potrivire.group(1).strip()
                break

    # PASUL 2: Completare cu modelul nostru ML Custom (pentru câmpurile rămase "Negasit")
    if nlp_custom is not None:
        doc_ml = nlp_custom(text)
        corespondenta_etichete = {
            "FURNIZOR": "Furnizor",
            "CLIENT": "Client",
            "CUI": "CUI",
            "NUMAR_FACTURA": "Numar_Factura",
            "DATA_FACTURA": "Data_Factura",
            "TOTAL_PLATA": "Total_Plata"
        }
        for ent in doc_ml.ents:
            camp_tabel = corespondenta_etichete.get(ent.label_)
            if camp_tabel and date_extrase[camp_tabel] == "Negasit":
                date_extrase[camp_tabel] = ent.text.strip()

    # PASUL 3: Plasă de siguranță în antet pentru Furnizor fără etichetă
    if date_extrase["Furnizor"] == "Negasit":
        primele_randuri = [r.strip() for r in text.split("\n") if r.strip()][:5]
        for rand in primele_randuri:
            if re.search(FORME_JURIDICE, rand, re.IGNORECASE) and not re.match(r"^(?:client|cumparator|beneficiar|bill\s+to)", rand, re.IGNORECASE):
                date_extrase["Furnizor"] = rand
                break

    if date_extrase["Furnizor"] == "Negasit":
        doc_gen = nlp_general("\n".join(text.split("\n")[:6]))
        for entitate in doc_gen.ents:
            if entitate.label_ == "ORG":
                date_extrase["Furnizor"] = entitate.text.strip()
                break

    # PASUL 4: Verificare scutire TVA și calcul matematic pentru Subtotal / TVA
    if date_extrase["TVA_VAT"] == "Negasit":
        if re.search(r"scutire\s+tva|neplatitor\s+de\s+tva|vat\s+exempt|0%\s*vat", text, re.IGNORECASE):
            date_extrase["TVA_VAT"] = "0,00"

    return completeaza_sume_contabile(date_extrase)


def salveaza_excel_formatat(lista_rezultate, fisier_iesire_excel):
    df = pd.DataFrame(lista_rezultate)
    with pd.ExcelWriter(fisier_iesire_excel, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Facturi")
        foaie = writer.sheets["Facturi"]
        # Ajustăm automat lățimea fiecărei coloane după cel mai lung text
        for coloana in foaie.columns:
            lungime_maxima = max(len(str(celula.value or "")) for celula in coloana)
            litera_coloana = coloana[0].column_letter
            foaie.column_dimensions[litera_coloana].width = lungime_maxima + 4


def proceseaza_folder_facturi(folder_intrare, fisier_iesire_excel):
    lista_rezultate = []

    for fisier in sorted(os.listdir(folder_intrare)):
        if fisier.lower().endswith(".pdf"):
            cale_completa = os.path.join(folder_intrare, fisier)
            text_factura = extrage_text_din_pdf(cale_completa)
            date_factura = analizeaza_text_factura(text_factura, fisier)
            lista_rezultate.append(date_factura)

    if lista_rezultate:
        salveaza_excel_formatat(lista_rezultate, fisier_iesire_excel)
        print(f"Succes! Tabelul complet a fost salvat în '{fisier_iesire_excel}'.")


if __name__ == "__main__":
    proceseaza_folder_facturi("invoices", "raport_facturi.xlsx")