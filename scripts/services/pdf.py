import logging
from playwright.async_api import async_playwright

async def html_a_pdf(html_content: str) -> bytes:
    """Genera un archivo PDF vectorial asegurando el cierre de recursos."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 794, "height": 1123})
            await page.set_content(html_content, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
            )
            logging.info(f"📄 Tamaño final del PDF: {len(pdf_bytes)/1024:.0f} KB")
            return pdf_bytes
        finally:
            await browser.close()