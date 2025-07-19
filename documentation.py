from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from typing import List
import base64
import requests
import re
import os
from fpdf import FPDF
from uuid import uuid4
from tempfile import TemporaryDirectory

# === Google Gemini Configuration ===
API_KEY = "AIzaSyBhOspAJs0Hkf8LtLZ7YfcYdB3BCQXSv_o"
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

    def add_analysis_page(self, structured_data, image_path):
        self.add_page()
        margin = 10
        image_width = 80
        spacing = 5

        x_image = self.w - margin - image_width
        y_image = 30
        x_text = margin
        y_text = y_image
        text_width = self.w - image_width - margin * 3

        self.image(image_path, x=x_image, y=y_image, w=image_width)
        self.set_xy(x_text, y_text)

        for label in MANDATORY_FIELDS:
            self.set_font("Arial", "B", 11)
            self.multi_cell(text_width, 8, f"{label}:")
            self.set_font("Arial", "", 11)
            content = structured_data.get(label, "Not detected or unavailable.")
            self.multi_cell(text_width, 8, content)
            self.ln(2)


def clean_and_structure(text: str):
    text = re.sub(r"\*+", "", text)
    structured = {}
    for label in MANDATORY_FIELDS:
        pattern = rf"{label}[:\-–]\s*(.+?)(?=\n[A-Z][a-z]+:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        structured[label] = match.group(1).strip() if match else "Not detected or unavailable."
    return structured


def analyze_image_via_gemini(image_path: str):
    with open(image_path, "rb") as img_file:
        image_base64 = base64.b64encode(img_file.read()).decode("utf-8")

    mime = "image/jpeg" if image_path.lower().endswith(".jpg") else "image/png"

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": image_base64
                        }
                    },
                    {
                        "text": PROMPT
                    }
                ]
            }
        ]
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(ENDPOINT, headers=headers, json=payload)

    if response.status_code == 200:
        raw = response.json()['candidates'][0]['content']['parts'][0]['text']
        return clean_and_structure(raw)
    else:
        print(f"API ERROR: {response.status_code}")
        return {label: "API error" for label in MANDATORY_FIELDS}


@app.post("/generate-pdf")
async def generate_pdf(files: List[UploadFile] = File(...)):
    with TemporaryDirectory() as tempdir:
        pdf = PDF()
        image_paths = []

        # Save uploaded files temporarily
        for file in files:
            ext = os.path.splitext(file.filename)[-1]
            filename = os.path.join(tempdir, f"{uuid4()}{ext}")
            with open(filename, "wb") as f:
                f.write(await file.read())
            image_paths.append(filename)

        # Analyze each image and build PDF
        for path in image_paths:
            analysis = analyze_image_via_gemini(path)
            pdf.add_analysis_page(analysis, path)

        output_path = os.path.join(tempdir, "output.pdf")
        pdf.output(output_path)

        return FileResponse(output_path, media_type="application/pdf", filename="design_analysis.pdf")
