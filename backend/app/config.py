import os
from pathlib import Path
from tempfile import gettempdir

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "sample_data"
UPLOAD_DIR = ROOT / "uploads"
REPORT_DIR = Path(gettempdir()) / 'scrutiny-reports' if os.environ.get('SCRUTINY_HOSTED') == '1' else ROOT / 'reports'
HISTORICAL_DIR = DATA_DIR / "historical"
ASSET_DIR = APP_DIR / "assets"
LOGO_PATH = ASSET_DIR / "dsec_logo.png"

# Template identity — mirrors Scritinyform.pdf issued by the department.
INSTITUTION_NAME = "DAYANANDA SAGAR COLLEGE OF ENGINEERING"
INSTITUTION_SUB = (
    "(An Autonomous Institution affiliated to Visvesvaraya Technological University, Belagavi)"
)
INSTITUTION_ADDRESS = "Shavige Malleshwara Hills, Kumaraswamy Layout, Bengaluru-560078"
DEPARTMENT_NAME = "DEPARTMENT OF COMPUTER SCIENCE & ENGINEERING"
FORM_TITLE = "QUESTION PAPER SCRUTINY FORMAT"

load_dotenv(ROOT / ".env")


class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    hots_threshold: float = float(os.getenv("HOTS_THRESHOLD", "0.40"))
    cie_max_marks: int = int(os.getenv("CIE_MAX_MARKS", "50"))

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
