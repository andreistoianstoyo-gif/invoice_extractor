import os
import re
import pdfplumber
import spacy
import pandas as pd

# 1. Încărcăm modelul general și modelul nostru ML Custom bilingv
nlp_general = spacy.load("ro_core_news_sm")
nlp_custom = spacy.load("model_facturi_ml") if os.path.exists("model_facturi_ml") else None

 #2. Dicționar bilingv (Română + Engleză) fără erori de formatare
SINONIME_CAMPURI = {
    "Furnizor": [
        r"(?:furnizor|firma|distribuitor|vanzator|prestator|emitent|unitate\s+emitenta|vendor|billed\s+by|billed\s+from|company|supplier|from)\s*[:\-]\s*\n?\s*([A-Za-z0-9][^\n\r\|]+)",
    ],
    "Client": [
        r"(?:client|cumparator|beneficiar|catre\s+abonat|catre|billed\s+to|bill\s+to|ship\s+to|customer|client\s+name)\s*[:\-]?\s*\n?\s*([A-Za-z0-9][^\n\r\(\|]+)",
    ],
    "CUI": [
        # Prinde "VAT no.: GB000000001", "VAT ID:", "Tax ID:", "EIN:" și CUI/CIF românesc (fără să treacă pe rândul următor)
        r"\b(?:c\.?u\.?i\.?|c\.?i\.?f\.?|cod\s+(?:inregistrare\s+)?fiscala?|cod\s+unic\s+de\s+inregistrare|vat\s*(?:id|no\.?|number|reg\.?(?:\s*no\.?)?)|tax\s*(?:id|no\.?)|ein|gst\s*(?:no\.?|id)?|reg\.?\s*no\.?)\s*[:\-\.\#]*\s*([A-Z]{2}[0-9A-Z \-]{5,15}|\d{2}\-\d{7}|(?:RO\s*)?\d{6,12})",
    ],
    "Numar_Factura": [
        r"seria\s*[:\-]?\s*([A-Za-z0-9]+\s+nr\.?\s*[:\-]?\s*[A-Za-z0-9\-]+)",
        # Prinde "Invoice no.: BF-2026-0412" chiar și când numărul e pe rândul următor sau în tabel
        r"\b(?:serie\s+si\s+numar|factura\s+fiscala\s+nr\.?|factura\s+nr\.?|nr\.\s*factura|numar\s+factura|doc\.\s*nr\.?|invoice\s*(?:no\.?|number|id|\#)|bill\s*(?:no\.?|\#))[\s:\-\.\#\|]*([A-Z0-9]+\-[A-Z0-9\-]+|[A-Za-z0-9\/]{3,20})",
        r"\bfactura\s*[:\-\#]+\s*([A-Za-z0-9\-\/]{3,20})",
    ],
    "Data_Factura": [
        # Prinde "03 Sep 2026", "October 24, 2026", "2026-11-10" și "12.10.2026"
        r"\b(?:data\s+emiterii|data\s+facturarii|data\s+document|data|invoice\s+date|issue\s+date|issued\s+on|date)[\s:\-\|]*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{4}|\d{4}[\.\/\-]\d{1,2}[\.\/\-]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+\d{4})",
    ],
    "Subtotal": [
        r"\b(?:subtotal|sub-total|total\s+fara\s+tva|baza\s+impozabila|valoare\s+fara\s+tva|net\s+amount|sub\s+total)[\s:\-\=\|]*(?:RON|LEI|EUR|USD|GBP|\$|€|£)?\s*(\d[\d\.,]*)",
    ],
    "TVA_VAT": [
        # Prinde atât "TVA: 190.00", cât și "VAT 20%  56.70 GBP" fără două puncte
        r"(?<!fara\s)\b(?:valoare\s+tva|tva|vat|sales\s+tax|tax|gst)\b(?:\s*\(?[\d\.,]+%\)?)?[\s:\-\=\.\|]+(?:RON|LEI|EUR|USD|GBP|\$|€|£)?\s*(\d[\d\.,]*)(?![\d\.,]|\s*%)",
    ],
    "Total_Plata": [
        r"\b(?:total\s+de\s+plata|total\s+general|total\s+factura|suma\s+de\s+plata|valoare\s+totala|de\s+achitat|total\s+due|amount\s+due|grand\s+total|balance\s+due|total\s+amount)[\s:\-\=\|]*(?:RON|LEI|EUR|USD|GBP|\$|€|£)?\s*(\d[\d\.,]*)",
        r"(?<!sub)(?<!sub\-)(?<!fara\s)\btotal\s*[:\-\=]\s*(?:RON|LEI|EUR|USD|GBP|\$|€|£)?\s*(\d[\d\.,]*)",
    ]
}

FORME_JURIDICE = r"\b(?:S\.?R\.?L\.?|S\.?A\.?|P\.?F\.?A\.?|I\.?I\.?|INC\.?|LLC|LTD\.?|CORP\.?|CORPORATION|GMBH|PLC|LLP)\b"

def extrage_text_din_pdf(cale_sau_bytes_pdf):
    text_complet = ""
    with pdfplumber.open(cale_sau_bytes_pdf) as pdf:
        for pagina in pdf.pages:
            text_pagina = pagina.extract_text()
            if text_pagina:
                text_complet += text_pagina + "\n"
    return text_complet


def detecteaza_stil_numar( date_extrase):
    """Detectează dacă factura folosește formatul EN (1,150.00) sau RO (1.500,00)."""
    for camp in ["Total_Plata", "Subtotal", "TVA_VAT"]:
        val = date_extrase.get(camp, "Negasit")
        if val != "Negasit" and "." in val:
            # Dacă punctul este urmat de exact 2 cifre la final, este format englezesc
            if re.search(r"\.\d{2}$", val.strip()):
                return "EN"
    return "RO"


def formateaza_numar(valoare_float, stil="RO"):
    """Formatează numărul calculat în stilul nativ al facturii (RO sau EN)."""
    format_en = f"{valoare_float:,.2f}"
    if stil == "EN":
        return format_en
    return format_en.replace(",", "X").replace(".", ",").replace("X", ".")


def transforma_in_numar(text_suma):
    if not text_suma or text_suma == "Negasit":
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
    stil = detecteaza_stil_numar(date_extrase)
    sub = transforma_in_numar(date_extrase["Subtotal"])
    tva = transforma_in_numar(date_extrase["TVA_VAT"])
    tot = transforma_in_numar(date_extrase["Total_Plata"])

    if sub is None and tot is not None and tva is not None:
        date_extrase["Subtotal"] = formateaza_numar(tot - tva, stil)
    elif tva is None and tot is not None and sub is not None:
        date_extrase["TVA_VAT"] = formateaza_numar(tot - sub, stil)
    elif sub is None and tva is None and tot is not None:
        date_extrase["Subtotal"] = date_extrase["Total_Plata"]
        date_extrase["TVA_VAT"] = "0.00" if stil == "EN" else "0,00"

    return date_extrase

def detecteaza_moneda(text):
    """Identifică moneda facturii (USD, EUR, GBP, RON) din zona totalului sau din întregul text."""
    mapare_simboluri = {
        "$": "USD", "USD": "USD",
        "€": "EUR", "EUR": "EUR",
        "£": "GBP", "GBP": "GBP",
        "RON": "RON", "LEI": "RON"
    }
    # 1. Căutăm moneda chiar pe rândul cu Totalul sau Subtotalul
    potrivire_total = re.search(
        r"(?:total|amount\s+due|balance\s+due|subtotal)[^\n\r]{0,30}?(RON|LEI|EUR|USD|GBP|\$|€|£)",
        text,
        re.IGNORECASE
    )
    if potrivire_total:
        simbol = potrivire_total.group(1).upper()
        return mapare_simboluri.get(simbol, simbol)

    # 2. Dacă nu e lângă total, căutăm în tot textul facturii
    for regex, cod_moneda in [
        (r"(?:\$|\bUSD\b)", "USD"),
        (r"(?:£|\bGBP\b)", "GBP"),
        (r"(?:€|\bEUR\b)", "EUR"),
        (r"\b(?:RON|LEI)\b", "RON"),
    ]:
        if re.search(regex, text, re.IGNORECASE):
            return cod_moneda

    return "RON"

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
        "Total_Plata": "Negasit",
        "Moneda": detecteaza_moneda(text)
    }

    # PASUL 1: Extracție prin reguli bilingve (Regex)
    for camp_standard, lista_sabloane in SINONIME_CAMPURI.items():
        for sablon in lista_sabloane:
            potrivire = re.search(sablon, text, re.IGNORECASE)
            if potrivire:
                date_extrase[camp_standard] = potrivire.group(1).strip()
                break

    # PASUL 2: Completare cu modelul nostru ML Custom bilingv
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

    # PASUL 3: Plasă de siguranță în antet pentru Furnizor fără etichetă (SRL, LLC, INC, LTD)
    if date_extrase["Furnizor"] == "Negasit":
        primele_randuri = [r.strip() for r in text.split("\n") if r.strip()][:6]
        for rand in primele_randuri:
            if re.search(FORME_JURIDICE, rand, re.IGNORECASE) and not re.match(
                r"^(?:client|cumparator|beneficiar|bill\s+to|billed\s+to|invoice)", rand, re.IGNORECASE
            ):
                date_extrase["Furnizor"] = rand
                break

    if date_extrase["Furnizor"] == "Negasit":
        doc_gen = nlp_general("\n".join(text.split("\n")[:6]))
        for entitate in doc_gen.ents:
            if entitate.label_ == "ORG":
                date_extrase["Furnizor"] = entitate.text.strip()
                break

    # PASUL 4: Scutire TVA / Tax Exempt și calcul matematic automat
    if date_extrase["TVA_VAT"] == "Negasit":
        if re.search(r"scutire\s+tva|neplatitor\s+de\s+tva|vat\s+exempt|tax\s+exempt|0%\s*(?:vat|tax)", text, re.IGNORECASE):
            stil = detecteaza_stil_numar(date_extrase)
            date_extrase["TVA_VAT"] = "0.00" if stil == "EN" else "0,00"

    return completeaza_sume_contabile(date_extrase)


def salveaza_excel_formatat(lista_rezultate, fisier_iesire_excel):
    df = pd.DataFrame(lista_rezultate)
    with pd.ExcelWriter(fisier_iesire_excel, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Facturi")
        foaie = writer.sheets["Facturi"]
        for coloana in foaie.columns:
            lungime_maxima = max(len(str(celula.value or "")) for celula in coloana)
            litera_coloana = coloana[0].column_letter
            foaie.column_dimensions[litera_coloana].width = lungime_maxima + 4


def proceseaza_folder_facturi(folder_intrare, fisier_iesire_excel):
    lista_rezultate = []
    if not os.path.exists(folder_intrare):
        return

    for fisier in sorted(os.listdir(folder_intrare)):
        if fisier.lower().endswith(".pdf"):
            cale_completa = os.path.join(folder_intrare, fisier)
            text_factura = extrage_text_din_pdf(cale_completa)
            date_factura = analizeaza_text_factura(text_factura, fisier)
            lista_rezultate.append(date_factura)

    if lista_rezultate:
        salveaza_excel_formatat(lista_rezultate, fisier_iesire_excel)
        print(f"Succes! Tabelul bilingv a fost salvat în '{fisier_iesire_excel}'.")


if __name__ == "__main__":
    proceseaza_folder_facturi("invoices", "raport_facturi.xlsx")
