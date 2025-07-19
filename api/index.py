from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import base64
import requests
import re
import os
from fpdf import FPDF
from uuid import uuid4
from io import BytesIO
from vercel_blob import put
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")  # Replace hardcoded API key
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"
PROMPT = (
    "Describe this room's materials, furniture, style, and provide a design summary. "
    "Respond in plain text without markdown or asterisks. Use labels like "
    "Materials:, Furniture:, Style:, Design Summary: clearly for each section."
)

MANDATORY_FIELDS = ["Materials", "Furniture", "Style", "Design Summary"]

app = FastAPI()

class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 16)
        self.cell(0, 10, "Maya Design Analysis", ln=True, align="C")
        self.ln(5)

    def add_analysis_page(self, structured_data, image_data, image_mime):
        self.add_page()
        margin = 10
        image_width = 80
        spacing = 5

        x_image = self.w - margin - image_width
        y_image = 30
        x_text = margin
        y_text = y_image
        text_width = self.w - image_width - margin * 3

        image_ext = image_mime.split('/')[-1].upper()
        self.image(name=BytesIO(image_data), x=x_image, y=y_image, w=image_width, type=image_ext)
        self.set_xy(x_text, y_text)
        for label in MANDATORY_FIELDS:
            self.set_font("Arial", "B", 11)
            self.multi_cell(text_width, 8, f"{label}:")
            self.set_font("Arial", "", 11)
            content = structured_data.get(label, "Not detected or unavailable.")
            self.multi_cell(text_width, 8, content)
            self.ln(2)

def clean_and_structure(text: str):
    structured = {}
    for label in MANDATORY_FIELDS:
        pattern = rf"{label}[:\-–]\s*(.+?)(?=\n[A-Z][a-z]+:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        structured[label] = match.group(1).strip() if match else "Not detected or unavailable."
    return structured

def analyze_image_via_gemini(image_data: bytes, mime: str):
    image_base64 = base64.b64encode(image_data).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": mime, "data": image_base64}},
                    {"text": PROMPT}
                ]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(ENDPOINT, headers=headers, json=payload)
    response.raise_for_status()
    raw = response.json()['candidates'][0]['content']['parts'][0]['text']
    return clean_and_structure(raw)

@app.post("/generate-pdf")
async def generate_pdf(files: List[UploadFile] = File(...)):
    pdf = PDF()
    for file in files:
        if file.content_type not in ["image/jpeg", "image/png"]:
            raise HTTPException(status_code=400, detail="Only JPEG or PNG files are supported")

        image_data = await file.read()
        mime = file.content_type
        analysis = analyze_image_via_gemini(image_data, mime)
        pdf.add_analysis_page(analysis, image_data, mime)

    # Save PDF to bytes
    pdf_data = pdf.output(dest='S').encode('latin1')
    pdf_buffer = BytesIO(pdf_data)

    blob_filename = f"design_analysis_{uuid4()}.pdf"
    blob_result = put(blob_filename, pdf_buffer.read(), {
        "access": "public",
        "token": os.getenv("BLOB_READ_WRITE_TOKEN")
    })
    return JSONResponse(content={"download_url": blob_result["url"], "filename": blob_filename})
