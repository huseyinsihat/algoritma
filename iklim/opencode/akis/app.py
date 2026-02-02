"""
Sürükle-bırak tuval + çift yönlü Mermaid senkronizasyon
Hüseyin SIHAT tarafından eğitsel faaliyetler için hazırlanmıştır.

Mimari: Görsel-Öncelikli (Etkileşimli Tuval) + Çift Yönlü Senkronizasyon
Teknoloji: Python 3.9+, Streamlit 1.30+, streamlit-flow
"""

from __future__ import annotations

import re
import time
import json
import base64
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
try:
    import requests
except ImportError:
    requests = None  # Optional dependency for export
try:
    from streamlit_flow import streamlit_flow
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
    from streamlit_flow.layouts import TreeLayout
    from streamlit_flow.state import StreamlitFlowState
except Exception as exc:
    raise ModuleNotFoundError(
        "Streamlit Flow component not available. "
        "Install with: pip install streamlit-flow-component"
    ) from exc

# ============================================================================
# HISTORY MANAGER (İŞ PAKETİ 5: UNDO/REDO)
# ============================================================================

from dataclasses import dataclass, field

@dataclass
class HistoryEntry:
    """Tek bir geçmiş kaydı."""
    code_text: str
    node_snapshot: List[dict] = field(default_factory=list)  # Serialized nodes
    edge_snapshot: List[dict] = field(default_factory=list)  # Serialized edges
    timestamp: float = field(default_factory=time.time)
    action: str = "edit"  # "add_node", "delete_edge", "update_label", etc.


class HistoryManager:
    """Undo/Redo yönetimi."""
    MAX_HISTORY = 20
    
    def __init__(self):
        self.undo_stack: List[HistoryEntry] = []
        self.redo_stack: List[HistoryEntry] = []
    
    def push(self, code_text: str, flow_state: StreamlitFlowState, action: str = "edit") -> None:
        """Yeni işlemi kaydet."""
        nodes = self._serialize_nodes(flow_state.nodes)
        edges = self._serialize_edges(flow_state.edges)
        entry = HistoryEntry(
            code_text=code_text,
            node_snapshot=nodes,
            edge_snapshot=edges,
            timestamp=time.time(),
            action=action,
        )
        self.undo_stack.append(entry)
        self.redo_stack.clear()  # Yeni işlem redo'yu temizler
        
        # Max limit kontrolü
        if len(self.undo_stack) > self.MAX_HISTORY:
            self.undo_stack.pop(0)
    
    def undo(self) -> Optional[HistoryEntry]:
        """Son işlemi geri al."""
        if len(self.undo_stack) < 2:  # En az 2 kayıt olmalı (başlangıç + en az 1 işlem)
            return None
        current = self.undo_stack.pop()
        self.redo_stack.append(current)
        return self.undo_stack[-1]
    
    def redo(self) -> Optional[HistoryEntry]:
        """Geri alınan işlemi yeniden yap."""
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        self.undo_stack.append(entry)
        return entry
    
    def can_undo(self) -> bool:
        """Undo yapılabilir mi?"""
        return len(self.undo_stack) >= 2
    
    def can_redo(self) -> bool:
        """Redo yapılabilir mi?"""
        return len(self.redo_stack) > 0
    
    def _serialize_nodes(self, nodes: List[StreamlitFlowNode]) -> List[dict]:
        """Düğümleri JSON-serializable dict'e dönüştür."""
        return [
            {
                "id": n.id,
                "pos": list(get_node_pos(n)),
                "content": (n.data or {}).get("content", n.id),
                "node_type": get_node_type(n),
            }
            for n in nodes
        ]
    
    def _serialize_edges(self, edges: List[StreamlitFlowEdge]) -> List[dict]:
        """Bağlantıları JSON-serializable dict'e dönüştür."""
        return [
            {
                "id": e.id,
                "source": e.source,
                "target": e.target,
                "label": get_edge_label(e),
                "type": get_edge_type(e),
                "mermaid_style": get_edge_mermaid_style(e),
            }
            for e in edges
        ]


# ============================================================================
# CONFIG
# ============================================================================

st.set_page_config(
    page_title="Sürükle-bırak tuval + çift yönlü Mermaid senkronizasyon",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 1.8rem; }
    section[data-testid="stSidebar"] { min-width: 280px; }
    section[data-testid="stSidebar"] .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] .stCaption { margin-bottom: 0.25rem; }
    .react-flow__pane { background: radial-gradient(circle at 20px 20px, #e8eef7 1px, transparent 1px); background-size: 24px 24px; }
    .react-flow__edge-path { stroke: #374151 !important; }
    .react-flow__edge .react-flow__edge-textbg { fill: #f3f6fb !important; }
    .react-flow__edge .react-flow__edge-text { fill: #111827 !important; font-weight: 600; }
    .react-flow__node { font-family: "Segoe UI", Arial, sans-serif; }
    .react-flow__node.selected { outline: 2px dashed #2563EB; outline-offset: 2px; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25); }
    .react-flow__edge.selected .react-flow__edge-path { stroke: #2563EB !important; stroke-width: 2.4 !important; }
    .react-flow__handle { width: 12px; height: 12px; background: #2563EB; border: 2px solid #ffffff; border-radius: 999px; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2); }
    .react-flow__handle::after { content: ""; position: absolute; width: 22px; height: 22px; top: -6px; left: -6px; border-radius: 999px; }
    .react-flow__node .react-flow__node-toolbar,
    .react-flow__node .node-toolbar,
    .react-flow__node .node-menu,
    .react-flow__node .react-flow__node-menu,
    .react-flow__node button.node-menu {
        display: none !important;
    }
    .stButton > button { display: inline-flex; align-items: center; gap: 6px; }
    .stButton > button[aria-label="Başla"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><circle cx='7' cy='7' r='5.5' fill='%2310B981' stroke='%23065F46' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Bitir"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><circle cx='7' cy='7' r='5.5' fill='%23F87171' stroke='%23991B1B' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="İşlem"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><rect x='2' y='3' width='10' height='8' rx='1.5' fill='%23E2E8F0' stroke='%23334155' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Karar"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><polygon points='7,1 13,7 7,13 1,7' fill='%23FDE68A' stroke='%2392400E' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Giriş/Çıkış"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><polygon points='2,3 12,3 10,11 0,11' fill='%23DBEAFE' stroke='%231E40AF' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Alt Süreç"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><rect x='2' y='3' width='10' height='8' rx='1' fill='%23E9D5FF' stroke='%235B21B6' stroke-width='1.5'/><line x1='4' y1='3' x2='4' y2='11' stroke='%235B21B6' stroke-width='1.2'/><line x1='10' y1='3' x2='10' y2='11' stroke='%235B21B6' stroke-width='1.2'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Veritabanı"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><ellipse cx='7' cy='3.5' rx='4.5' ry='2' fill='%23DBEAFE' stroke='%231E40AF' stroke-width='1.2'/><rect x='2.5' y='3.5' width='9' height='7' fill='%23DBEAFE' stroke='%231E40AF' stroke-width='1.2'/><ellipse cx='7' cy='10.5' rx='4.5' ry='2' fill='%23DBEAFE' stroke='%231E40AF' stroke-width='1.2'/></svg>") no-repeat center/contain;
    }
    .stButton > button[aria-label="Bağlantı"]::before {
        content: "";
        width: 16px; height: 16px; display: inline-block;
        background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'><circle cx='7' cy='7' r='3' fill='%23FFF1C7' stroke='%2392400E' stroke-width='1.5'/></svg>") no-repeat center/contain;
    }
    
    /* Panel geçiş animasyonları (İP-7) */
    .stColumn {
        transition: all 0.3s ease-in-out;
    }
    
    /* Mod değişikliği toast bildirimi */
    .mode-toast {
        animation: slideIn 0.3s ease-out;
    }
    
    @keyframes slideIn {
        from {
            transform: translateY(-20px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }
    
    /* Kod paneli açılma */
    .code-panel {
        animation: expandPanel 0.3s ease-out;
    }
    
    @keyframes expandPanel {
        from {
            max-height: 0;
            opacity: 0;
        }
        to {
            max-height: 500px;
            opacity: 1;
        }
    }
    
    /* Silme butonu vurgulama */
    button[type="secondary"]:hover {
        background-color: #ffe6e6 !important;
        border-color: #ff6666 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULT_CODE = """flowchart TD
    A([Başlangıç])
    A --> B[/Veri Al/]
    B --> C[İşlemi Yap]
    C --> D{Kontrol?}
    D -->|Evet| E[[Alt Süreç]]
    D -->|Hayır| F([Bitir])
    E --> F
"""

DIRECTION_TO_LAYOUT = {
    "TD": "down",
    "TB": "down",
    "BT": "up",
    "LR": "right",
    "RL": "left",
}

# Genişletilmiş node pattern'leri (Mermaid flowchart sözdizimi)
NODE_PATTERNS = {
    "stadium": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\(\[([^\]]+)\]\)"),       # A([Label])
    "subprocess": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\[\[([^\]]+)\]\]"),   # A[[Label]]
    "database": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\[\(([^)]+)\)\]"),      # A[(Label)]
    "connector": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\(\(([^)]+)\)\)"),     # A((Label))
    "parallelogram": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\[/([^/]+)/\]"),   # A[/Label/]
    "decision": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\{([^}]+)\}"),          # A{Label}
    "default": re.compile(r"^\s*([A-Za-z0-9_]+)\s*\[([^\]]+)\]"),          # A[Label]
}

# Genişletilmiş edge pattern'leri
EDGE_PATTERNS = {
    "labeled_dotted": re.compile(r"^\s*([A-Za-z0-9_]+)\s*-\.->\|([^|]+)\|\s*([A-Za-z0-9_]+)"),
    "labeled_thick": re.compile(r"^\s*([A-Za-z0-9_]+)\s*==>\|([^|]+)\|\s*([A-Za-z0-9_]+)"),
    "labeled_bidirectional": re.compile(r"^\s*([A-Za-z0-9_]+)\s*<-->\|([^|]+)\|\s*([A-Za-z0-9_]+)"),
    "labeled": re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\|([^|]+)\|\s*([A-Za-z0-9_]+)"),
    "dotted": re.compile(r"^\s*([A-Za-z0-9_]+)\s*-\.->\s*([A-Za-z0-9_]+)"),
    "thick": re.compile(r"^\s*([A-Za-z0-9_]+)\s*==>\s*([A-Za-z0-9_]+)"),
    "bidirectional": re.compile(r"^\s*([A-Za-z0-9_]+)\s*<-->\s*([A-Za-z0-9_]+)"),
    "default": re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\s*([A-Za-z0-9_]+)"),
}

# Eski pattern'ler (backward compat)
NODE_PATTERN = NODE_PATTERNS["default"]
EDGE_PATTERN = EDGE_PATTERNS["labeled"]

# Mermaid pattern → node_type mapping
PATTERN_TO_TYPE = {
    "stadium": "terminal",
    "subprocess": "subprocess",
    "database": "database",
    "connector": "connector",
    "parallelogram": "io",
    "decision": "decision",
    "default": "default",
}

NODE_TYPES = {
    "default": "İşlem",
    "decision": "Karar",
    "terminal": "Terminal",
    "io": "Giriş/Çıkış",
    "subprocess": "Alt Süreç",
    "connector": "Bağlantı",
    "database": "Veritabanı",
}

SAFE_NODE_TYPES = {
    "default", 
    "decision", 
    "terminal", 
    "io", 
    "subprocess", 
    "connector", 
    "database", 
    "input",  # Backward compatibility
    "output"  # Backward compatibility
}

LEARNING_MODES = [
    "Başlangıç (Sadece Tuval)",
    "Karma (Tuval + Kod Önizleme)",
    "Hibrit (Tuval + Kod Edit)",
    "Uzman (Kod Öncelikli)",
]

# İŞ PAKETİ 8: Şablon Sistemi
TEMPLATES = {
    "Boş Proje": {
        "code": "flowchart TD\n    A([Başlangıç])",
        "description": "Temiz bir başlangıç",
    },
    "Sabah Rutini": {
        "code": """flowchart TD
    A([Uyan])
    A --> B[/Alarmı kapat/]
    B --> C[Diș fırçala]
    C --> D{Kahve hazır mı?}
    D -->|Evet| E[İç]
    D -->|Hayır| F[Demle]
    E --> G([Gün Başladı])
    F --> E""",
        "description": "Günlük rutin akışı",
    },
    "ATM Para Çekme": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Kart tak/]
    B --> C[/Şifre gir/]
    C --> D{Şifre doğru mu?}
    D -->|Hayır| C
    D -->|Evet| E[İşlem seç]
    E --> F{Bakiye yeterli mi?}
    F -->|Hayır| G[Uyarı göster]
    F -->|Evet| H[Parayı ver]
    H --> I([Bitir])""",
        "description": "ATM adımları",
    },
    "Online Sipariş": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Ürün ara/]
    B --> C[Sepete ekle]
    C --> D{Stok var mı?}
    D -->|Hayır| B
    D -->|Evet| E[/Adres gir/]
    E --> F[/Ödeme yap/]
    F --> G[(Siparişi kaydet)]
    G --> H([Tamamlandı])""",
        "description": "E-ticaret akışı",
    },
    "Kargo Teslimi": {
        "code": """flowchart TD
    A([Başlangıç])
    A --> B[/Adres doğrula/]
    B --> C{Evde mi?}
    C -->|Evet| D[İmza al]
    C -->|Hayır| E[[Not bırak]]
    D --> F([Teslim])
    E --> F""",
        "description": "Teslimat süreci",
    },
    "Randevu Sistemi": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Kimlik bilgisi al/]
    B --> C{Slot uygun mu?}
    C -->|Hayır| D[/Tarih seç/]
    D --> C
    C -->|Evet| E[(Randevu kaydet)]
    E --> F([Bitir])""",
        "description": "Randevu planlama",
    },
    "Mutfak Tarifi": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Malzemeleri hazırla/]
    B --> C[Karıştır]
    C --> D{Kıvam iyi mi?}
    D -->|Hayır| C
    D -->|Evet| E[Servis et]
    E --> F([Bitti])""",
        "description": "Yemek hazırlama",
    },
    "Sınav Kayıt": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Form doldur/]
    B --> C{Belgeler tam mı?}
    C -->|Hayır| B
    C -->|Evet| D[(Başvuruyu kaydet)]
    D --> E([Tamam])""",
        "description": "Kayıt süreci",
    },
    "Depo Stok": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Ürün giriş/]
    B --> C[(Stok güncelle)]
    C --> D{Minimum altı mı?}
    D -->|Evet| E[[Tedarik uyarısı]]
    D -->|Hayır| F([Bitir])
    E --> F""",
        "description": "Stok kontrol akışı",
    },
    "Kütüphane Ödünç": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Üye kartı al/]
    B --> C{Kitap mevcut mu?}
    C -->|Hayır| D[Rezervasyon]
    C -->|Evet| E[Ödünç ver]
    E --> F[(Kayıt oluştur)]
    D --> F
    F --> G([Bitir])""",
        "description": "Ödünç alma süreci",
    },
    "Çağrı Merkezi": {
        "code": """flowchart TD
    A([Başla])
    A --> B[/Arama al/]
    B --> C{Sorun çözüldü mü?}
    C -->|Evet| D([Bitir])
    C -->|Hayır| E[[Uzman aktar]]
    E --> F([Bitir])""",
        "description": "Destek akışı",
    },
}

# ============================================================================
# PERSISTENCE (localStorage & Auto-Save)
# ============================================================================

AUTOSAVE_DIR = Path(".streamlit/autosave")
AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
AUTOSAVE_FILE = AUTOSAVE_DIR / "project_autosave.json"
AUTO_SAVE_INTERVAL = 30  # saniye


def auto_save_to_file() -> None:
    """Projeyi dosya sistemine otomatik kayıt et."""
    try:
        save_data = {
            "code_text": st.session_state.code_text,
            "direction": st.session_state.direction,
            "mode": st.session_state.mode,
            "project_title": st.session_state.project_title,
            "timestamp": int(time.time()),
        }
        AUTOSAVE_FILE.write_text(json.dumps(save_data, ensure_ascii=False, indent=2))
    except Exception as e:
        st.warning(f"⚠️ Auto-save hatası: {e}")


def load_autosave() -> Optional[Dict]:
    """Otomatik kaydı yükle."""
    if AUTOSAVE_FILE.exists():
        try:
            data = json.loads(AUTOSAVE_FILE.read_text())
            return data
        except Exception:
            return None
    return None


def show_recovery_modal() -> None:
    """Kurtarma modalı göster."""
    autosave = load_autosave()
    if autosave and "recovery_shown" not in st.session_state:
        st.session_state.recovery_shown = True
        timestamp = time.strftime('%H:%M:%S', time.localtime(autosave["timestamp"]))
        with st.container():
            st.warning(f"📂 Kaydedilmemiş proje bulundu ({timestamp})")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("♻️ Geri Yükle", key="recover_yes"):
                    sync_code_text(autosave["code_text"])
                    st.session_state.direction = autosave["direction"]
                    st.session_state.mode = autosave["mode"]
                    st.session_state.project_title = autosave["project_title"]
                    st.session_state.flow_state = build_flow_state_from_code(autosave["code_text"])
                    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                    st.toast("✅ Proje geri yüklendi")
                    st.rerun()
            with col2:
                if st.button("Yeni Başla", key="recover_no"):
                    AUTOSAVE_FILE.unlink(missing_ok=True)
                    st.session_state.recovery_shown = True
                    st.rerun()


# ============================================================================
# EXPORT MODULES (İŞ PAKETİ 6: PNG/SVG EXPORT)
# ============================================================================

def export_as_png_via_api(flow_state: StreamlitFlowState, direction: str) -> bytes:
    """
    Tuval içeriğini PNG olarak export et (Mermaid.ink API üzerinden).
    
    Gerekli: requests kütüphanesi
    API: https://mermaid.ink
    """
    if requests is None:
        raise ImportError("requests kütüphanesi gereklidir. pip install requests")
    
    mermaid_code = generate_mermaid(flow_state, direction)
    encoded = base64.urlsafe_b64encode(mermaid_code.encode()).decode()
    img_url = f"https://mermaid.ink/img/{encoded}"
    
    try:
        response = requests.get(img_url, timeout=15)
        if response.status_code == 200:
            return response.content
        else:
            raise Exception(f"API Hatası: {response.status_code}")
    except requests.Timeout:
        raise Exception("API timeout - İnternet bağlantısı kontrol edin")
    except requests.RequestException as e:
        raise Exception(f"İstek hatası: {str(e)[:100]}")


def export_as_svg_via_api(flow_state: StreamlitFlowState, direction: str) -> str:
    """
    Tuval içeriğini SVG olarak export et (Mermaid.ink API üzerinden).
    
    Gerekli: requests kütüphanesi
    API: https://mermaid.ink
    """
    if requests is None:
        raise ImportError("requests kütüphanesi gereklidir. pip install requests")
    
    mermaid_code = generate_mermaid(flow_state, direction)
    encoded = base64.urlsafe_b64encode(mermaid_code.encode()).decode()
    svg_url = f"https://mermaid.ink/svg/{encoded}"
    
    try:
        response = requests.get(svg_url, timeout=15)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"API Hatası: {response.status_code}")
    except requests.Timeout:
        raise Exception("API timeout - İnternet bağlantısı kontrol edin")
    except requests.RequestException as e:
        raise Exception(f"İstek hatası: {str(e)[:100]}")


# ============================================================================
# STATE
# ============================================================================


def get_node_type(node: StreamlitFlowNode) -> str:
    data = node.data or {}
    if "node_type" in data:
        return data.get("node_type", "default")
    if hasattr(node, "type"):
        value = getattr(node, "type")
        if value:
            return value
    if hasattr(node, "node_type"):
        value = getattr(node, "node_type")
        if value:
            return value
    return "default"


def set_node_type(node: StreamlitFlowNode, node_type: str) -> None:
    # streamlit-flow sadece default/input/output kabul ediyor
    # Gerçek tipi data içinde sakla, node.type her zaman "default" olsun
    if hasattr(node, "node_type"):
        try:
            setattr(node, "node_type", "default")
        except Exception:
            pass
    if hasattr(node, "type"):
        try:
            setattr(node, "type", "default")
        except Exception:
            pass
    data = node.data or {}
    if data.get("node_type") != node_type:
        node.data = {**data, "node_type": node_type}


def get_node_pos(node: StreamlitFlowNode) -> Tuple[int, int]:
    pos = getattr(node, "pos", None)
    if pos:
        return tuple(pos)
    position = getattr(node, "position", None)
    if isinstance(position, dict):
        return (int(position.get("x", 0)), int(position.get("y", 0)))
    data = node.data or {}
    data_pos = data.get("pos")
    if data_pos and isinstance(data_pos, (list, tuple)) and len(data_pos) == 2:
        return (int(data_pos[0]), int(data_pos[1]))
    return (0, 0)


def merge_style(existing: Dict, defaults: Dict) -> Dict:
    merged = dict(existing or {})
    for key, value in defaults.items():
        merged.setdefault(key, value)
    return merged


def parse_style_width(style: Optional[Dict], fallback: int = 140) -> int:
    if not style:
        return fallback
    raw = style.get("width")
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        match = re.search(r"(\\d+)", raw)
        if match:
            return int(match.group(1))
    return fallback


def get_node_style(node_type: str) -> Dict:
    """Sembol tipine göre CSS stil döndür."""

    # Varsayılan stil (İşlem kutusu)
    base = {
        "padding": "8px 12px",
        "borderRadius": "12px",
        "border": "1px solid #94A3B8",
        "background": "#EEF2FF",
        "boxShadow": "0 4px 14px rgba(15, 23, 42, 0.12)",
        "fontWeight": 600,
        "minWidth": "110px",
        "textAlign": "center",
    }
    
    # Tip bazlı özelleştirmeler
    styles = {
        "decision": {
            "border": "2px solid #F59E0B",
            "background": "#FFF1C7",
            "width": "140px",
            "height": "80px",
            "padding": "0",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "clipPath": "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)",
            "color": "#92400E",
        },
        "terminal": {
            "border": "2px solid #10B981",
            "background": "#D1FAE5",
            "borderRadius": "50px",
            "padding": "10px 20px",
            "fontWeight": 700,
            "color": "#065F46",
            "minWidth": "120px",
        },
        "io": {
            "border": "2px solid #2563EB",
            "background": "#DBEAFE",
            "clipPath": "polygon(10% 0%, 100% 0%, 90% 100%, 0% 100%)",
            "padding": "12px 20px",
            "fontWeight": 600,
            "color": "#1E40AF",
            "minWidth": "140px",
        },
        "subprocess": {
            "border": "2px solid #7C3AED",
            "borderLeft": "6px solid #7C3AED",
            "borderRight": "6px solid #7C3AED",
            "background": "#E9D5FF",
            "borderRadius": "8px",
            "padding": "10px 18px",
            "fontWeight": 600,
            "color": "#5B21B6",
            "fontStyle": "italic",
        },
        "connector": {
            "border": "3px solid #F59E0B",
            "background": "#FFF1C7",
            "borderRadius": "50%",
            "width": "50px",
            "height": "50px",
            "padding": "0",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "fontWeight": 700,
            "fontSize": "18px",
            "color": "#92400E",
        },
        "database": {
            "border": "2px solid #1E40AF",
            "background": "#DBEAFE",
            "borderRadius": "12px 12px 50% 50% / 12px 12px 15% 15%",
            "padding": "15px 20px",
            "fontWeight": 600,
            "color": "#1E3A8A",
            "minHeight": "60px",
            "minWidth": "120px",
        },
    }
    
    if node_type in styles:
        base.update(styles[node_type])

    return base


SELECTED_NODE_STYLE = {
    "border": "2px solid #2563EB",
    "boxShadow": "0 0 0 3px rgba(37, 99, 235, 0.25)",
    "outline": "2px dashed #2563EB",
    "outlineOffset": "2px",
}


def normalize_state(state: StreamlitFlowState) -> None:
    if state is None:
        return
    for node in state.nodes:
        data = node.data or {}
        if "content" not in data:
            data["content"] = node.id
        node_type = data.get("node_type") or get_node_type(node)
        data["node_type"] = node_type
        data.setdefault("pos", list(get_node_pos(node)))
        node.data = data
        set_node_type(node, node_type)
        if hasattr(node, "connectable"):
            node.connectable = True
        if hasattr(node, "selectable"):
            node.selectable = True
        if hasattr(node, "deletable"):
            node.deletable = True
        # Her zaman stil uygula - renkler kaybolmasın
        node_style = get_node_style(node_type)
        if hasattr(node, "style"):
            current_style = getattr(node, "style", {})
            # Mevcut pozisyon/seçim bilgilerini koru, sadece renk/şekil güncellet
            node.style = {**current_style, **node_style}
        else:
            node.style = node_style
        if getattr(node, "selected", False):
            node.style = {**node.style, **SELECTED_NODE_STYLE}

    for edge in state.edges:
        label = get_edge_label(edge)
        set_edge_label(edge, label)
        if hasattr(edge, "deletable"):
            edge.deletable = True
        if hasattr(edge, "label_show_bg"):
            edge.label_show_bg = True
        if hasattr(edge, "label_bg_style"):
            edge.label_bg_style = merge_style(
                getattr(edge, "label_bg_style", {}),
                {"fill": "#F3F6FB", "stroke": "#CFD8E6", "strokeWidth": 1, "rx": 6, "ry": 6},
            )
        if hasattr(edge, "style"):
            edge.style = merge_style(
                getattr(edge, "style", {}),
                {"stroke": "#6B7A90", "strokeWidth": 1.6},
            )


def update_selected_from_state(state: StreamlitFlowState) -> None:
    if state is None:
        st.session_state.selected_node_id = None
        st.session_state.selected_edge_id = None
        return
    selected_nodes = [n.id for n in state.nodes if getattr(n, "selected", False)]
    selected_edges = [e.id for e in state.edges if getattr(e, "selected", False)]
    st.session_state.selected_node_id = selected_nodes[0] if selected_nodes else None
    st.session_state.selected_edge_id = selected_edges[0] if selected_edges else None


def get_edge_data(edge: StreamlitFlowEdge) -> Dict:
    data = getattr(edge, "data", None)
    if isinstance(data, dict):
        return data
    return {}


def get_edge_label(edge: StreamlitFlowEdge) -> str:
    label = getattr(edge, "label", None)
    if label:
        return label
    data = get_edge_data(edge)
    return data.get("label", "")


def get_edge_type(edge: StreamlitFlowEdge) -> str:
    value = getattr(edge, "type", None)
    if value:
        return value
    data = get_edge_data(edge)
    return data.get("type", "default")


def get_edge_mermaid_style(edge: StreamlitFlowEdge) -> str:
    data = get_edge_data(edge)
    return data.get("mermaid_style", "default")


def set_edge_mermaid_style(edge: StreamlitFlowEdge, style: str) -> None:
    data = get_edge_data(edge)
    if data.get("mermaid_style") != style:
        edge.data = {**data, "mermaid_style": style}


def set_edge_label(edge: StreamlitFlowEdge, label: str) -> None:
    if hasattr(edge, "label"):
        try:
            setattr(edge, "label", label)
        except Exception:
            pass
    data = get_edge_data(edge)
    if data.get("label") != label:
        edge.data = {**data, "label": label}


def set_edge_type(edge: StreamlitFlowEdge, edge_type: str) -> None:
    if hasattr(edge, "type"):
        try:
            setattr(edge, "type", edge_type)
        except Exception:
            pass
    data = get_edge_data(edge)
    if data.get("type") != edge_type:
        edge.data = {**data, "type": edge_type}


def initialize_state() -> None:
    defaults = {
        "project_title": "AkilliAkis",
        "direction": "TD",
        "mode": LEARNING_MODES[2],
        "code_text": DEFAULT_CODE.strip(),
        "code_editor": DEFAULT_CODE.strip(),
        "last_code_hash": None,
        "last_graph_hash": None,
        "last_edit_source": None,
        "last_save_timestamp": int(time.time()),
        "last_auto_save": int(time.time()),
        "node_counter": 0,
        "selected_node_id": None,
        "selected_edge_id": None,
        "last_selected_node_id": None,
        "last_selected_edge_id": None,
        "quick_edit_label": "",
        "quick_edge_label": "",
        "ignore_next_graph_change": False,
        "recovery_shown": False,
        "history_manager": None,  # İP-5: Undo/Redo (İlk initialize'da oluşturulacak)
        "export_png_data": None,
        "export_svg_data": None,
        "export_error": None,
        "auto_download_mermaid": False,
        "import_buffer": None,
        "import_filename": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "flow_state" not in st.session_state:
        st.session_state.flow_state = build_flow_state_from_code(st.session_state.code_text)
        normalize_state(st.session_state.flow_state)
    
    # İP-5: HistoryManager oluştur ve ilk state'i kaydet
    if st.session_state.history_manager is None:
        st.session_state.history_manager = HistoryManager()
        # İlk state'i history'ye ekle
        st.session_state.history_manager.push(
            st.session_state.code_text,
            st.session_state.flow_state,
            "init"
        )

def sync_code_text(new_code: str) -> None:
    """Keep Mermaid code and editor widget in sync."""
    st.session_state.code_text = new_code
    st.session_state.code_editor = new_code
    st.session_state.last_code_hash = hash(new_code)


# ============================================================================
# MERMAID PARSER / GENERATOR
# ============================================================================


def parse_mermaid(code: str) -> Tuple[Optional[StreamlitFlowState], Optional[str], str]:
    """
    Genişletilmiş Mermaid parser - tüm flowchart syntax'ını destekler.
    
    Desteklenen düğüm tipleri:
    - [Label]: dikdörtgen (varsayılan)
    - {Label}: baklava (karar)
    - ([Label]): stadium (başlangıç/bitiş)
    - [[Label]]: alt süreç
    - [(Label)]: veritabanı (silindir)
    - [/Label/]: paralel kenar (girdi)
    
    Desteklenen bağlantılar:
    - -->: normal bağlantı
    - -->|label|: etiketli bağlantı
    - -.->: kesikli bağlantı
    - ==>: kalın bağlantı
    - <-->: çift yönlü bağlantı
    """
    lines = [line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("%%")]
    nodes: Dict[str, StreamlitFlowNode] = {}
    edges: List[StreamlitFlowEdge] = []
    direction = "TD"
    errors = []

    for line_num, line in enumerate(lines, 1):
        # Yön tespiti
        if line.startswith("flowchart") or line.startswith("graph"):
            parts = line.split()
            if len(parts) > 1:
                direction = parts[1].upper()
            continue
        
        # Subgraph başlangıcı (şimdilik atla)
        if line.startswith("subgraph") or line == "end":
            continue

        # Bağlantı tespiti (önce, çünkü düğüm içerebilir)
        edge_found = False
        for edge_type, pattern in EDGE_PATTERNS.items():
            edge_match = pattern.search(line)
            if edge_match:
                if edge_type.startswith("labeled"):
                    source, label, target = edge_match.group(1), edge_match.group(2), edge_match.group(3)
                    style_map = {
                        "labeled": "default",
                        "labeled_dotted": "dotted",
                        "labeled_thick": "thick",
                        "labeled_bidirectional": "bidirectional",
                    }
                    mermaid_style = style_map.get(edge_type, "default")
                elif edge_type in ["default", "dotted", "thick", "bidirectional"]:
                    source, target = edge_match.group(1), edge_match.group(2)
                    label = ""
                    mermaid_style = edge_type
                else:
                    continue
                
                edge_id = f"{source}_{target}_{len(edges)}"
                new_edge = StreamlitFlowEdge(
                    id=edge_id,
                    source=source,
                    target=target,
                    edge_type="smoothstep",
                    marker_end={"type": "arrowclosed"},
                    label=label,
                )
                set_edge_mermaid_style(new_edge, mermaid_style)
                edges.append(new_edge)
                # Implicit düğümleri oluştur
                for node_id in [source, target]:
                    if node_id not in nodes:
                        nodes[node_id] = StreamlitFlowNode(
                            id=node_id,
                            pos=(0, len(nodes) * 100),
                            data={"content": node_id, "node_type": "default"},
                            type="default",
                        )
                edge_found = True
                break
        
        if edge_found:
            continue

        # Düğüm tespiti
        node_found = False
        for node_type_name, pattern in NODE_PATTERNS.items():
            node_match = pattern.search(line)
            if node_match:
                node_id = node_match.group(1)
                label = node_match.group(2).strip()
                
                # Node type belirleme (PATTERN_TO_TYPE mapping kullan)
                node_type = PATTERN_TO_TYPE.get(node_type_name, "default")
                
                nodes[node_id] = StreamlitFlowNode(
                    id=node_id,
                    pos=(0, len(nodes) * 100),
                    data={"content": label, "node_type": node_type},
                    type="default",  # streamlit-flow sadece default/input/output kabul ediyor
                )
                node_found = True
                break
        
        # Eğer parse edilemedi
        if not node_found and line and not line.startswith("%%"):
            errors.append(f"Satır {line_num}: '{line[:50]}...' parse edilemedi")

    if not nodes and not edges:
        return None, "Kodda geçerli düğüm veya bağlantı bulunamadı.", direction

    if errors and len(errors) <= 5:
        # Sadece az sayıda hata varsa uyarı göster
        pass  # UI'da gösterilecek

    state = StreamlitFlowState(list(nodes.values()), edges)
    return state, None, direction


def build_flow_state_from_code(code: str) -> StreamlitFlowState:
    state, error, direction = parse_mermaid(code)
    if error or state is None:
        state = StreamlitFlowState(
            [
                StreamlitFlowNode(
                    id="A",
                    pos=(0, 0),
                    data={"content": "Başlangıç", "node_type": "terminal"},
                    type="default",
                )
            ],
            [],
        )
        normalize_state(state)
        return state
    st.session_state.direction = direction
    normalize_state(state)
    return state


def build_flow_state_from_entry(entry: "HistoryEntry") -> StreamlitFlowState:
    if not entry or not entry.node_snapshot:
        return build_flow_state_from_code(entry.code_text if entry else DEFAULT_CODE.strip())
    nodes: List[StreamlitFlowNode] = []
    edges: List[StreamlitFlowEdge] = []
    for n in entry.node_snapshot:
        node = StreamlitFlowNode(
            id=n["id"],
            pos=tuple(n.get("pos", (0, 0))),
            data={"content": n.get("content", n["id"]), "node_type": n.get("node_type", "default")},
            type="default",
        )
        nodes.append(node)
    for e in entry.edge_snapshot:
        edge = StreamlitFlowEdge(
            id=e["id"],
            source=e["source"],
            target=e["target"],
            edge_type=e.get("type", "smoothstep"),
            marker_end={"type": "arrowclosed"},
            label=e.get("label", ""),
        )
        set_edge_label(edge, e.get("label", ""))
        set_edge_type(edge, e.get("type", "smoothstep"))
        if "mermaid_style" in e:
            set_edge_mermaid_style(edge, e.get("mermaid_style", "default"))
        edges.append(edge)
    state = StreamlitFlowState(nodes, edges)
    normalize_state(state)
    return state


def generate_mermaid(state: StreamlitFlowState, direction: str) -> str:
    """Flow state → Mermaid kod dönüşümü."""
    lines = [f"flowchart {direction}"]

    # Node type → Mermaid syntax mapping
    TYPE_TO_SYNTAX = {
        "terminal": lambda nid, lbl: f"{nid}([{lbl}])",
        "io": lambda nid, lbl: f"{nid}[/{lbl}/]",
        "subprocess": lambda nid, lbl: f"{nid}[[{lbl}]]",
        "database": lambda nid, lbl: f"{nid}[({lbl})]",
        "connector": lambda nid, lbl: f"{nid}(({lbl}))",
        "decision": lambda nid, lbl: f"{nid}{{{lbl}}}",
        "default": lambda nid, lbl: f"{nid}[{lbl}]",
    }

    for node in sorted(state.nodes, key=lambda n: n.id):
        label = (node.data or {}).get("content", node.id)
        node_type = get_node_type(node)
        syntax_fn = TYPE_TO_SYNTAX.get(node_type, TYPE_TO_SYNTAX["default"])
        lines.append(f"    {syntax_fn(node.id, label)}")

    for edge in state.edges:
        label = get_edge_label(edge)
        mermaid_style = get_edge_mermaid_style(edge)
        arrow_map = {
            "default": "-->",
            "dotted": "-.->",
            "thick": "==>",
            "bidirectional": "<-->",
        }
        arrow = arrow_map.get(mermaid_style, "-->")
        if label:
            lines.append(f"    {edge.source} {arrow}|{label}| {edge.target}")
        else:
            lines.append(f"    {edge.source} {arrow} {edge.target}")

    return "\n".join(lines)


def graph_hash(state: StreamlitFlowState) -> int:
    nodes_sig = sorted(
        (
            n.id,
            (n.data or {}).get("content", ""),
            get_node_type(n),
            get_node_pos(n),
        )
        for n in state.nodes
    )
    edges_sig = sorted(
        (
            e.id,
            e.source,
            e.target,
            get_edge_label(e),
            get_edge_type(e),
        )
        for e in state.edges
    )
    return hash((tuple(nodes_sig), tuple(edges_sig)))


# ============================================================================
# CANVAS ACTIONS
# ============================================================================


def next_node_id(prefix: str = "N") -> str:
    st.session_state.node_counter += 1
    candidate = f"{prefix}{st.session_state.node_counter}"
    existing_ids = {node.id for node in st.session_state.flow_state.nodes}
    while candidate in existing_ids:
        st.session_state.node_counter += 1
        candidate = f"{prefix}{st.session_state.node_counter}"
    return candidate


def get_node_prefix(node_type: str) -> str:
    prefix_map = {
        "terminal": "T",
        "io": "IO",
        "subprocess": "SP",
        "connector": "C",
        "database": "DB",
        "decision": "K",
    }
    return prefix_map.get(node_type, "N")


def get_default_label(node_type: str) -> str:
    label_map = {
        "terminal": "Başla",
        "io": "Giriş/Çıkış",
        "subprocess": "Alt Süreç",
        "connector": "A",
        "database": "Veritabanı",
        "decision": "Karar?",
        "default": "Yeni Adım",
    }
    return label_map.get(node_type, "Yeni Adım")


def get_smart_position() -> Tuple[float, float]:
    """
    Mevcut düğümlere göre akıllı pozisyon hesapla.
    Overlap olmaması için boş alan bul.
    """
    if not st.session_state.flow_state.nodes:
        return (80, 80)
    
    # Mevcut tüm pozisyonları topla
    positions = [get_node_pos(node) for node in st.session_state.flow_state.nodes]
    
    # Yön bazlı strateji
    direction = st.session_state.direction
    
    if direction == "TD":  # Yukarıdan aşağı - altına ekle
        max_y = max(pos[1] for pos in positions)
        return (80, max_y + 140)
    elif direction == "BT":  # Aşağıdan yukarı - üstüne ekle
        min_y = min(pos[1] for pos in positions)
        return (80, min_y - 140)
    elif direction == "LR":  # Soldan sağa - sağına ekle
        max_x = max(pos[0] for pos in positions)
        return (max_x + 220, 80)
    elif direction == "RL":  # Sağdan sola - soluna ekle
        min_x = min(pos[0] for pos in positions)
        return (min_x - 220, 80)
    else:
        # Varsayılan: en altta
        max_y = max(pos[1] for pos in positions)
        return (80, max_y + 140)


def add_node_with_label(node_type: str, default_label: str) -> None:
    """Önceden tanımlı etiketle düğüm ekle."""
    st.session_state.ignore_next_graph_change = True
    node_id = next_node_id("T" if node_type == "terminal" else "N")
    pos = get_smart_position()  # Akıllı pozisyonlama
    new_node = StreamlitFlowNode(
        id=node_id,
        pos=pos,
        data={"content": default_label, "node_type": node_type},
        type="default",  # streamlit-flow sadece default/input/output kabul ediyor
    )
    set_node_type(new_node, node_type)
    if hasattr(new_node, "connectable"):
        new_node.connectable = True
    if hasattr(new_node, "selectable"):
        new_node.selectable = True
    if hasattr(new_node, "deletable"):
        new_node.deletable = True
    if hasattr(new_node, "style"):
        new_node.style = merge_style(getattr(new_node, "style", {}), get_node_style(node_type))
    # KRİTİK: Yeni liste oluştur - Streamlit state değişikliğini farketsin
    current_nodes = list(st.session_state.flow_state.nodes)
    current_nodes.append(new_node)
    st.session_state.flow_state = StreamlitFlowState(
        nodes=current_nodes,
        edges=list(st.session_state.flow_state.edges)
    )
    # State'i güncelle
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # History
    st.session_state.history_manager.push(
        st.session_state.code_text,
        st.session_state.flow_state,
        f"add_node({node_type})"
    )


def add_node(node_type: str) -> None:
    """Yeni düğüm ekle."""
    st.session_state.ignore_next_graph_change = True
    node_id = next_node_id(get_node_prefix(node_type))
    label = get_default_label(node_type)
    
    pos = get_smart_position()  # Akıllı pozisyonlama
    new_node = StreamlitFlowNode(
        id=node_id,
        pos=pos,
        data={"content": label, "node_type": node_type},
        type="default",  # streamlit-flow sadece default/input/output kabul ediyor
    )
    set_node_type(new_node, node_type)
    if hasattr(new_node, "connectable"):
        new_node.connectable = True
    if hasattr(new_node, "selectable"):
        new_node.selectable = True
    if hasattr(new_node, "deletable"):
        new_node.deletable = True
    if hasattr(new_node, "style"):
        new_node.style = merge_style(getattr(new_node, "style", {}), get_node_style(node_type))
    # KRİTİK: Yeni liste oluştur - Streamlit state değişikliğini farketsin
    current_nodes = list(st.session_state.flow_state.nodes)
    current_nodes.append(new_node)
    st.session_state.flow_state = StreamlitFlowState(
        nodes=current_nodes,
        edges=list(st.session_state.flow_state.edges)
    )
    # State'i güncelle
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # History
    st.session_state.history_manager.push(
        st.session_state.code_text,
        st.session_state.flow_state,
        f"add_node({node_type})"
    )


def add_node_and_connect(
    node_type: str,
    attach_from: Optional[str],
    label_override: Optional[str] = None,
    edge_label: Optional[str] = None,
    edge_type: str = "smoothstep",
) -> None:
    """Seçili düğümden yeni düğüm ekle ve bağla."""
    st.session_state.ignore_next_graph_change = True
    node_id = next_node_id(get_node_prefix(node_type))
    label = label_override or get_default_label(node_type)
    
    if attach_from:
        src_node = next((n for n in st.session_state.flow_state.nodes if n.id == attach_from), None)
        src_pos = get_node_pos(src_node) if src_node else (0, 0)
        
        # Yön bazlı offset hesaplama - DÜZELTİLMİŞ
        if st.session_state.direction == "LR":  # Soldan sağa
            x_offset = 220
            y_offset = 0
        elif st.session_state.direction == "RL":  # Sağdan sola
            x_offset = -220
            y_offset = 0
        elif st.session_state.direction == "TD":  # Yukarıdan aşağı
            x_offset = 0
            y_offset = 140
        elif st.session_state.direction == "BT":  # Aşağıdan yukarı
            x_offset = 0
            y_offset = -140
        else:  # Varsayılan TD
            x_offset = 0
            y_offset = 140
        
        pos = (src_pos[0] + x_offset, src_pos[1] + y_offset)
    else:
        pos = get_smart_position()  # Akıllı pozisyonlama
    new_node = StreamlitFlowNode(
        id=node_id,
        pos=pos,
        data={"content": label, "node_type": node_type},
        type="default",  # streamlit-flow sadece default/input/output kabul ediyor
    )
    set_node_type(new_node, node_type)
    if hasattr(new_node, "connectable"):
        new_node.connectable = True
    if hasattr(new_node, "selectable"):
        new_node.selectable = True
    if hasattr(new_node, "deletable"):
        new_node.deletable = True
    if hasattr(new_node, "style"):
        new_node.style = merge_style(getattr(new_node, "style", {}), get_node_style(node_type))
    # KRİTİK: Yeni liste oluştur - Streamlit state değişikliğini farketsin
    current_nodes = list(st.session_state.flow_state.nodes)
    current_nodes.append(new_node)
    st.session_state.flow_state = StreamlitFlowState(
        nodes=current_nodes,
        edges=list(st.session_state.flow_state.edges)
    )
    if attach_from:
        add_edge(attach_from, node_id, edge_label, edge_type=edge_type, rerun=False, push_history=False)
    # State'i güncelle
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # History
    st.session_state.history_manager.push(
        st.session_state.code_text,
        st.session_state.flow_state,
        f"add_node_connect({node_type})"
    )


def add_edge(
    source: str,
    target: str,
    label: Optional[str],
    edge_type: str = "smoothstep",
    rerun: bool = True,
    push_history: bool = True,
) -> None:
    st.session_state.ignore_next_graph_change = True
    edge_id = f"{source}_{target}_{len(st.session_state.flow_state.edges)}"
    new_edge = StreamlitFlowEdge(
        id=edge_id,
        source=source,
        target=target,
        edge_type=edge_type,
        marker_end={"type": "arrowclosed"},
        label=label or "",
    )
    set_edge_label(new_edge, label or "")
    set_edge_mermaid_style(new_edge, "default")
    if hasattr(new_edge, "deletable"):
        new_edge.deletable = True
    if hasattr(new_edge, "label_show_bg"):
        new_edge.label_show_bg = True
    if hasattr(new_edge, "label_bg_style"):
        new_edge.label_bg_style = merge_style(
            getattr(new_edge, "label_bg_style", {}),
            {"fill": "#F3F6FB", "stroke": "#CFD8E6", "strokeWidth": 1, "rx": 6, "ry": 6},
        )
    if hasattr(new_edge, "style"):
        new_edge.style = merge_style(
            getattr(new_edge, "style", {}),
            {"stroke": "#6B7A90", "strokeWidth": 1.6},
        )
    # KRİTİK: Yeni liste oluştur - Streamlit state değişikliğini farketsin
    current_edges = list(st.session_state.flow_state.edges)
    current_edges.append(new_edge)
    st.session_state.flow_state = StreamlitFlowState(
        nodes=list(st.session_state.flow_state.nodes),
        edges=current_edges
    )
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    if push_history:
        st.session_state.history_manager.push(
            st.session_state.code_text,
            st.session_state.flow_state,
            f"add_edge({source}->{target})"
        )
    if rerun:
        st.rerun()


def update_node(
    node_id: str,
    label: str,
    node_type: str,
    width: Optional[int] = None,
    source_position: Optional[str] = None,
    target_position: Optional[str] = None,
) -> None:
    # KRİTİK: Yeni liste oluştur - mutate etme!
    st.session_state.ignore_next_graph_change = True
    updated_nodes = []
    for node in st.session_state.flow_state.nodes:
        if node.id == node_id:
            node.data = {**(node.data or {}), "content": label}
            set_node_type(node, node_type)
            if hasattr(node, "style"):
                node.style = merge_style(getattr(node, "style", {}), get_node_style(node_type))
                if width is not None:
                    node.style = {**node.style, "width": f"{int(width)}px"}
            if source_position and hasattr(node, "source_position"):
                node.source_position = source_position
            if target_position and hasattr(node, "target_position"):
                node.target_position = target_position
        updated_nodes.append(node)
    
    st.session_state.flow_state = StreamlitFlowState(
        nodes=updated_nodes,
        edges=list(st.session_state.flow_state.edges)
    )
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    st.session_state.history_manager.push(
        st.session_state.code_text,
        st.session_state.flow_state,
        f"update_node({node_id})"
    )
    st.rerun()


def update_edge(edge_id: str, label: str) -> None:
    st.session_state.ignore_next_graph_change = True
    for edge in st.session_state.flow_state.edges:
        if edge.id == edge_id:
            set_edge_label(edge, label)
            break
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # İP-5: History'ye işlemi kaydet
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"update_edge({edge_id})")
    st.rerun()


def update_edge_type(edge_id: str, edge_type: str) -> None:
    st.session_state.ignore_next_graph_change = True
    for edge in st.session_state.flow_state.edges:
        if edge.id == edge_id:
            set_edge_type(edge, edge_type)
            break
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # İP-5: History'ye işlemi kaydet
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"update_edge_type({edge_id})")
    st.rerun()


def update_edge_full(
    edge_id: str,
    label: str,
    edge_type: str,
    source: str,
    target: str,
) -> None:
    st.session_state.ignore_next_graph_change = True
    for edge in st.session_state.flow_state.edges:
        if edge.id == edge_id:
            set_edge_label(edge, label)
            set_edge_type(edge, edge_type)
            edge.source = source
            edge.target = target
            break
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"update_edge({edge_id})")
    st.rerun()


def reverse_edge(edge_id: str) -> None:
    st.session_state.ignore_next_graph_change = True
    for edge in st.session_state.flow_state.edges:
        if edge.id == edge_id:
            edge.source, edge.target = edge.target, edge.source
            break
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # İP-5: History'ye işlemi kaydet
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"reverse_edge({edge_id})")
    st.rerun()


def update_edge_endpoints(edge_id: str, source: str, target: str) -> None:
    st.session_state.ignore_next_graph_change = True
    for edge in st.session_state.flow_state.edges:
        if edge.id == edge_id:
            edge.source = source
            edge.target = target
            break
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # İP-5: History'ye işlemi kaydet
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"update_edge_endpoints({edge_id})")
    st.rerun()


def delete_node(node_id: str) -> None:
    """
    Düğümü ve ilişkili tüm bağlantılarını siler.
    
    İşlem Sırası:
    1. Bu düğümü kaynak veya hedef olarak kullanan tüm kenarları kaldır
    2. Düğümü flow_state.nodes'dan kaldır
    3. Mermaid kodunu yeniden oluştur
    4. Hash'leri güncelle
    5. Seçim temizle
    """
    st.session_state.ignore_next_graph_change = True
    # İlişkili kenarları bul ve sil
    related_edges = [
        e for e in st.session_state.flow_state.edges 
        if e.source == node_id or e.target == node_id
    ]
    for edge in related_edges:
        st.session_state.flow_state.edges.remove(edge)
    
    # Düğümü sil
    node_to_remove = next(
        (n for n in st.session_state.flow_state.nodes if n.id == node_id), 
        None
    )
    if node_to_remove:
        st.session_state.flow_state.nodes.remove(node_to_remove)
    
    # Seçimi temizle
    st.session_state.selected_node_id = None
    
    # Sync
    sync_code_text(generate_mermaid(
        st.session_state.flow_state,
        st.session_state.direction
    ))
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    # İP-5: History'ye işlemi kaydet
    st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"delete_node({node_id})")
    st.toast(f"🗑️ '{node_id}' düğümü silindi")
    st.rerun()


def delete_edge(edge_id: str) -> None:
    """Bağlantıyı siler."""
    st.session_state.ignore_next_graph_change = True
    edge_to_remove = next(
        (e for e in st.session_state.flow_state.edges if e.id == edge_id),
        None
    )
    if edge_to_remove:
        source_id = edge_to_remove.source
        target_id = edge_to_remove.target
        st.session_state.flow_state.edges.remove(edge_to_remove)
        
        # Seçimi temizle
        st.session_state.selected_edge_id = None
        
        # Sync
        sync_code_text(generate_mermaid(
            st.session_state.flow_state,
            st.session_state.direction
        ))
        st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
        # İP-5: History'ye işlemi kaydet
        st.session_state.history_manager.push(st.session_state.code_text, st.session_state.flow_state, f"delete_edge({edge_id})")
        st.toast(f"🗑️ '{source_id}' → '{target_id}' bağlantısı silindi")
        st.rerun()


# ============================================================================
# UI
# ============================================================================


def sidebar_ui() -> None:
    with st.sidebar.expander("🎓 Öğrenme Modu", expanded=True):
        mode = st.radio(
            "Öğrenme Modu",
            LEARNING_MODES,
            index=LEARNING_MODES.index(st.session_state.mode),
            label_visibility="collapsed",
        )
        st.session_state.mode = mode

    with st.sidebar.expander("⚙️ Ayarlar", expanded=True):
        direction_labels = {
            "Yukarıdan Aşağı (TD)": "TD",
            "Soldan Sağa (LR)": "LR",
            "Sağdan Sola (RL)": "RL",
            "Aşağıdan Yukarı (BT)": "BT",
        }
        current_label = next(
            (k for k, v in direction_labels.items() if v == st.session_state.direction),
            "Yukarıdan Aşağı (TD)",
        )
        selected_label = st.selectbox(
            "🧭 Yön",
            list(direction_labels.keys()),
            index=list(direction_labels.keys()).index(current_label),
        )
        new_direction = direction_labels[selected_label]
        if new_direction != st.session_state.direction:
            st.session_state.direction = new_direction
            sync_code_text(generate_mermaid(st.session_state.flow_state, new_direction))

    with st.sidebar.expander("📚 Şablonlar", expanded=True):
        selected_template = st.selectbox(
            "Şablon Seç",
            list(TEMPLATES.keys()),
            format_func=lambda x: f"{x} - {TEMPLATES[x]['description']}",
        )

        if st.button("📋 Şablonu Uygula", use_container_width=True):
            template = TEMPLATES[selected_template]
            sync_code_text(template["code"])
            st.session_state.flow_state = build_flow_state_from_code(template["code"])
            normalize_state(st.session_state.flow_state)
            st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
            st.session_state.history_manager.push(
                st.session_state.code_text,
                st.session_state.flow_state,
                f"load_template({selected_template})"
            )
            st.toast(f"✅ '{selected_template}' şablonu yüklendi")
            st.rerun()

    with st.sidebar.expander("🧾 Proje", expanded=True):
        project_title = st.text_input("Proje Adı", value=st.session_state.project_title)
        if project_title != st.session_state.project_title:
            st.session_state.project_title = project_title

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Kaydet", use_container_width=True):
                try:
                    file_name = f"{st.session_state.project_title}.mmd"
                    with open(file_name, "w", encoding="utf-8") as f:
                        f.write(st.session_state.code_text)
                    st.session_state.last_save_timestamp = int(time.time())
                    st.session_state.auto_download_mermaid = True
                    st.session_state.history_manager.push(
                        st.session_state.code_text, 
                        st.session_state.flow_state, 
                        f"save({st.session_state.project_title})"
                    )
                    st.toast("✅ Proje kaydedildi")
                except Exception as exc:
                    st.error(f"Kaydetme hatası: {exc}")
        with col2:
            if st.button("Yeni", use_container_width=True):
                sync_code_text(DEFAULT_CODE.strip())
                st.session_state.flow_state = build_flow_state_from_code(st.session_state.code_text)
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                st.toast("🆕 Yeni proje başlatıldı")
                st.rerun()

    with st.sidebar.expander("⬇️ Dışa Aktar", expanded=st.session_state.auto_download_mermaid):
        export_format = st.selectbox("Format", ["Mermaid (.mmd)", "PNG", "SVG"])
        
        if export_format == "Mermaid (.mmd)":
            st.download_button(
                "Mermaid İndir",
                st.session_state.code_text,
                f"{st.session_state.project_title}.mmd",
                "text/plain",
                use_container_width=True,
                key="download_mmd"
            )
        elif export_format == "PNG":
            if st.button("PNG Oluştur", use_container_width=True, key="generate_png"):
                if requests is None:
                    st.session_state.export_error = "PNG oluşturma için 'requests' kütüphanesi gerekli."
                    st.session_state.export_png_data = None
                else:
                    try:
                        st.session_state.export_png_data = export_as_png_via_api(
                            st.session_state.flow_state,
                            st.session_state.direction,
                        )
                        st.session_state.export_error = None
                    except Exception as e:
                        st.session_state.export_error = f"PNG export hatası: {str(e)[:120]}"
                        st.session_state.export_png_data = None
            if st.session_state.export_png_data:
                st.download_button(
                    "PNG İndir",
                    st.session_state.export_png_data,
                    f"{st.session_state.project_title}.png",
                    "image/png",
                    use_container_width=True,
                    key="download_png"
                )
            if st.session_state.export_error:
                st.error(st.session_state.export_error)
        elif export_format == "SVG":
            if st.button("SVG Oluştur", use_container_width=True, key="generate_svg"):
                if requests is None:
                    st.session_state.export_error = "SVG oluşturma için 'requests' kütüphanesi gerekli."
                    st.session_state.export_svg_data = None
                else:
                    try:
                        st.session_state.export_svg_data = export_as_svg_via_api(
                            st.session_state.flow_state,
                            st.session_state.direction,
                        )
                        st.session_state.export_error = None
                    except Exception as e:
                        st.session_state.export_error = f"SVG export hatası: {str(e)[:120]}"
                        st.session_state.export_svg_data = None
            if st.session_state.export_svg_data:
                st.download_button(
                    "SVG İndir",
                    st.session_state.export_svg_data,
                    f"{st.session_state.project_title}.svg",
                    "image/svg+xml",
                    use_container_width=True,
                    key="download_svg"
                )
            if st.session_state.export_error:
                st.error(st.session_state.export_error)

        if st.session_state.auto_download_mermaid:
            st.download_button(
                "Mermaid İndir (Otomatik)",
                st.session_state.code_text,
                f"{st.session_state.project_title}.mmd",
                "text/plain",
                use_container_width=True,
                key="download_mmd_auto"
            )
            st.markdown(
                """
                <script>
                setTimeout(function() {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const btn = btns.find(b => b.textContent && b.textContent.includes('Mermaid İndir (Otomatik)'));
                    if (btn) { btn.click(); }
                }, 300);
                </script>
                """,
                unsafe_allow_html=True,
            )
            st.session_state.auto_download_mermaid = False

    with st.sidebar.expander("⬆️ İçe Aktar", expanded=False):
        upload = st.file_uploader("Mermaid (.mmd) Yükle", type=["mmd", "txt"], key="import_mmd")
        if upload is not None:
            st.session_state.import_buffer = upload.getvalue()
            st.session_state.import_filename = upload.name

        if st.button("İçe Aktar", use_container_width=True):
            incoming_bytes = st.session_state.get("import_buffer")
            if not incoming_bytes:
                st.warning("Önce bir dosya seçin.")
            else:
                try:
                    incoming = incoming_bytes.decode("utf-8")
                    parsed_state, error, direction = parse_mermaid(incoming)
                    if error:
                        st.error(error)
                    else:
                        sync_code_text(incoming)
                        st.session_state.flow_state = parsed_state
                        st.session_state.direction = direction
                        normalize_state(st.session_state.flow_state)
                        st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                        filename = st.session_state.get("import_filename", "import")
                        st.session_state.history_manager.push(
                            st.session_state.code_text,
                            st.session_state.flow_state,
                            f"import({filename})"
                        )
                        st.session_state.import_buffer = None
                        st.toast("✅ Dosya içe aktarıldı")
                        st.rerun()
                except Exception as exc:
                    st.error(f"İçe aktarma hatası: {str(exc)[:120]}")

    with st.sidebar.expander("ℹ️ Durum", expanded=False):
        st.info(
            f"""
            **Durum:**
            - Son kayıt: {time.strftime('%H:%M:%S', time.localtime(st.session_state.last_save_timestamp))}
            """
        )


def toolbar_ui() -> None:
    """Kompakt sembol paleti - temiz ve düzenli."""
    history_mgr = st.session_state.history_manager

    def add_from_palette(node_type: str, label_override: Optional[str] = None) -> None:
        selected_node_id = st.session_state.get("selected_node_id")
        if selected_node_id:
            st.session_state.ignore_next_graph_change = True
            add_node_and_connect(node_type, selected_node_id, label_override=label_override)
            st.session_state.selected_node_id = None
            st.session_state.last_selected_node_id = None
        else:
            st.session_state.ignore_next_graph_change = True
            if node_type == "terminal" and label_override:
                add_node_with_label("terminal", label_override)
            else:
                add_node(node_type)
        st.rerun()
    
    main_col, side_col = st.columns([7, 1])
    with main_col:
        row1 = st.columns([1, 1, 1, 1])
        with row1[0]:
            if st.button("Başla", use_container_width=True, help="Algoritma başlangıcı"):
                add_from_palette("terminal", "Başla")
        with row1[1]:
            if st.button("Giriş/Çıkış", use_container_width=True, help="Veri al/yaz"):
                add_from_palette("io")
        with row1[2]:
            if st.button("İşlem", use_container_width=True, help="Hesaplama/atama"):
                add_from_palette("default")
        with row1[3]:
            if st.button("Karar", use_container_width=True, help="Koşul kontrolü"):
                add_from_palette("decision")

        row2 = st.columns([1, 1, 1, 1])
        with row2[0]:
            if st.button("Alt Süreç", use_container_width=True, help="Fonksiyon çağrısı"):
                add_from_palette("subprocess")
        with row2[1]:
            if st.button("Veritabanı", use_container_width=True, help="Veri saklama"):
                add_from_palette("database")
        with row2[2]:
            if st.button("Bağlantı", use_container_width=True, help="Akış noktası"):
                add_from_palette("connector")
        with row2[3]:
            if st.button("Bitir", use_container_width=True, help="Algoritma sonu"):
                add_from_palette("terminal", "Bitir")

    with side_col:
        if st.button("Geri Al", use_container_width=True, disabled=not history_mgr.can_undo(), help="Geri al"):
            entry = history_mgr.undo()
            if entry:
                st.session_state.ignore_next_graph_change = True
                sync_code_text(entry.code_text)
                st.session_state.flow_state = build_flow_state_from_entry(entry)
                normalize_state(st.session_state.flow_state)
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                st.session_state.last_edit_source = "undo"
                st.toast(f"↶ Geri: {entry.action}")
                st.rerun()

        if st.button("İleri Al", use_container_width=True, disabled=not history_mgr.can_redo(), help="İleri al"):
            entry = history_mgr.redo()
            if entry:
                st.session_state.ignore_next_graph_change = True
                sync_code_text(entry.code_text)
                st.session_state.flow_state = build_flow_state_from_entry(entry)
                normalize_state(st.session_state.flow_state)
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                st.session_state.last_edit_source = "redo"
                st.toast(f"↷ İleri: {entry.action}")
                st.rerun()
    
def properties_panel() -> None:
    st.subheader("🎛️ Özellik Paneli")
    nodes = st.session_state.flow_state.nodes
    edges = st.session_state.flow_state.edges

    node_ids = [node.id for node in nodes]
    edge_ids = [edge.id for edge in edges]

    tab_nodes, tab_edges = st.tabs(["Düğümler", "Bağlantılar"])

    with tab_nodes:
        if not node_ids:
            st.info("Düğüm yok. Tuvalden düğüm ekleyin.")
        else:
            default_node_id = st.session_state.get("selected_node_id") or node_ids[0]
            if st.session_state.get("prop_node_id") != default_node_id:
                st.session_state.prop_node_id = default_node_id
            selected_node_id = st.selectbox("Düğüm Seç", node_ids, key="prop_node_id")
            selected_node = next(node for node in nodes if node.id == selected_node_id)
            label_value = (selected_node.data or {}).get("content", selected_node.id)
            new_label = st.text_input("Etiket", value=label_value, key="prop_node_label")
            selected_type = get_node_type(selected_node)
            new_type = st.selectbox(
                "Tip",
                list(NODE_TYPES.keys()),
                index=list(NODE_TYPES.keys()).index(selected_type),
                key="prop_node_type",
            )
            width_value = parse_style_width(getattr(selected_node, "style", {}), fallback=140)
            new_width = st.number_input(
                "Genişlik",
                min_value=80,
                max_value=260,
                value=width_value,
                step=10,
                key="prop_node_width",
            )
            positions = ["top", "bottom", "left", "right"]
            src_pos = getattr(selected_node, "source_position", "bottom")
            tgt_pos = getattr(selected_node, "target_position", "top")
            col_pos_a, col_pos_b = st.columns(2)
            with col_pos_a:
                new_src_pos = st.selectbox(
                    "Kaynak Konum",
                    positions,
                    index=positions.index(src_pos) if src_pos in positions else 1,
                    key="prop_node_src",
                )
            with col_pos_b:
                new_tgt_pos = st.selectbox(
                    "Hedef Konum",
                    positions,
                    index=positions.index(tgt_pos) if tgt_pos in positions else 0,
                    key="prop_node_tgt",
                )
            col_update, col_delete = st.columns(2)
            with col_update:
                if st.button("Düğümü Güncelle", use_container_width=True):
                    update_node(
                        selected_node_id,
                        new_label,
                        new_type,
                        width=new_width,
                        source_position=new_src_pos,
                        target_position=new_tgt_pos,
                    )
            with col_delete:
                if st.button("Düğümü Sil", use_container_width=True, type="secondary"):
                    delete_node(selected_node_id)

    with tab_edges:
        if not edge_ids:
            st.info("Bağlantı yok. Düğümler arasında bağlantı kurun.")
        else:
            default_edge_id = st.session_state.get("selected_edge_id") or edge_ids[0]
            if st.session_state.get("prop_edge_id") != default_edge_id:
                st.session_state.prop_edge_id = default_edge_id
            selected_edge_id = st.selectbox("Bağlantı Seç", edge_ids, key="prop_edge_id")
            selected_edge = next(edge for edge in edges if edge.id == selected_edge_id)
            edge_label_value = get_edge_label(selected_edge)
            new_edge_label = st.text_input("Etiket", value=edge_label_value, key="prop_edge_label")
            edge_type_value = get_edge_type(selected_edge)
            edge_type_options = ["smoothstep", "default", "straight", "step", "simplebezier"]
            new_edge_type = st.selectbox(
                "Tip",
                edge_type_options,
                index=edge_type_options.index(edge_type_value) if edge_type_value in edge_type_options else 0,
                key="prop_edge_type",
            )
            src_value = selected_edge.source
            tgt_value = selected_edge.target
            new_src = st.selectbox("Kaynak", node_ids, index=node_ids.index(src_value), key="prop_edge_src")
            new_tgt = st.selectbox("Hedef", node_ids, index=node_ids.index(tgt_value), key="prop_edge_tgt")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                if st.button("Bağlantıyı Güncelle", use_container_width=True):
                    update_edge_full(
                        selected_edge_id,
                        new_edge_label.strip(),
                        new_edge_type,
                        new_src,
                        new_tgt,
                    )
            with col_b:
                if st.button("Ters Çevir", use_container_width=True):
                    reverse_edge(selected_edge_id)
            with col_c:
                if st.button("Bağlantıyı Sil", use_container_width=True, type="secondary"):
                    delete_edge(selected_edge_id)

def edge_builder() -> None:
    st.subheader("🔗 Bağlantı Ekle")
    node_ids = [node.id for node in st.session_state.flow_state.nodes]
    if len(node_ids) < 2:
        st.info("Bağlantı için en az 2 düğüm gerekir.")
        return

    selected_node_id = st.session_state.get("selected_node_id")
    if "edge_source" not in st.session_state and selected_node_id in node_ids:
        st.session_state.edge_source = selected_node_id
    source_index = node_ids.index(st.session_state.edge_source) if st.session_state.get("edge_source") in node_ids else 0
    target_options = [nid for nid in node_ids if nid != node_ids[source_index]]
    target_default = target_options[0] if target_options else node_ids[source_index]
    if "edge_target" not in st.session_state and target_default in node_ids:
        st.session_state.edge_target = target_default

    source = st.selectbox("Kaynak Düğüm", node_ids, index=source_index, key="edge_source")
    target = st.selectbox("Hedef Düğüm", node_ids, index=node_ids.index(target_default), key="edge_target")
    edge_type = st.selectbox("Bağlantı Tipi", ["smoothstep", "default", "straight", "step", "simplebezier"], index=0)
    label = st.text_input("Etiket (opsiyonel)")
    if st.button("Bağlantı Oluştur", use_container_width=True):
        if source == target:
            st.warning("Kaynak ve hedef aynı olamaz.")
            return
        add_edge(source, target, label.strip() if label else None, edge_type=edge_type)

def main() -> None:
    st.title("Pratik Akış Şeması")
    st.caption("Hüseyin SIHAT tarafından eğitsel faaliyetler için hazırlanmıştır.")

    # İŞ PAKETİ 9: Klavye Kısayolları [ENHANCED]
    st.markdown("""
    <script>
    document.addEventListener('keydown', function(e) {
        // Ctrl+S: Kaydet (save button click)
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            // Button seçici - streamlit dinamik olacağından text bazlı search kullanıyoruz
            const buttons = Array.from(document.querySelectorAll('button'));
            const saveBtn = buttons.find(btn => btn.textContent.includes('Kaydet'));
            if (saveBtn) {
                saveBtn.click();
                console.log('💾 Ctrl+S: Kaydetme başlatıldı');
            }
        }
        
        // Ctrl+Z: Geri Al (undo button click)
        if (e.ctrlKey && e.key === 'z' && !e.shiftKey) {
            e.preventDefault();
            const buttons = Array.from(document.querySelectorAll('button'));
            const undoBtn = buttons.find(btn => btn.textContent.includes('Geri Al') || btn.textContent.includes('↶'));
            if (undoBtn && !undoBtn.disabled) {
                undoBtn.click();
                console.log('↶ Ctrl+Z: Geri alındı');
            }
        }
        
        // Ctrl+Y veya Ctrl+Shift+Z: İleri Al (redo button click)
        if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'z')) {
            e.preventDefault();
            const buttons = Array.from(document.querySelectorAll('button'));
            const redoBtn = buttons.find(btn => btn.textContent.includes('İleri Al') || btn.textContent.includes('↷'));
            if (redoBtn && !redoBtn.disabled) {
                redoBtn.click();
                console.log('↷ Ctrl+Y: İleri alındı');
            }
        }
        
        // Delete: Seçili öğeyi sil
        if (e.key === 'Delete') {
            const buttons = Array.from(document.querySelectorAll('button'));
            const deleteBtn = buttons.find(btn => btn.textContent.includes('Düğümü Sil') || btn.textContent.includes('Bağlantıyı Sil') || btn.textContent.includes('🗑️'));
            if (deleteBtn) {
                deleteBtn.click();
                console.log('🗑️ Delete: Silme başlatıldı');
            }
        }
    });
    </script>
    """, unsafe_allow_html=True)

    st.markdown("""
    <script>
    (function() {
        const map = {
            "Edit Node": "Düğümü Düzenle",
            "Edit Edge": "Bağlantıyı Düzenle",
            "Node Content": "Düğüm Metni",
            "Node Width": "Düğüm Genişliği",
            "Node Type": "Düğüm Tipi",
            "Edge Label": "Bağlantı Etiketi",
            "Edge Type": "Bağlantı Tipi",
            "Source Position": "Kaynak Konum",
            "Target Position": "Hedef Konum",
            "Draggable": "Sürüklenebilir",
            "Connectable": "Bağlanabilir",
            "Deletable": "Silinebilir",
            "Animated": "Animasyon",
            "Label BG": "Etiket Arka Plan",
            "Delete Node": "D???m? Sil",
            "Delete Edge": "Ba?lant?y? Sil",
            "Close": "Kapat",
            "Save Changes": "Kaydet",
            "Add Node": "Düğüm Ekle",
            "Add Edge": "Bağlantı Ekle",
            "Pane": "Tuval"
        };
        const replaceText = (node) => {
            if (!node) return;
            if (node.nodeType === Node.TEXT_NODE) {
                const t = node.textContent;
                if (map[t]) node.textContent = map[t];
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.childNodes && node.childNodes.length) {
                    node.childNodes.forEach(replaceText);
                }
            }
        };
        const observer = new MutationObserver((mutations) => {
            for (const m of mutations) {
                m.addedNodes && m.addedNodes.forEach(replaceText);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        replaceText(document.body);
    })();
    </script>
    """, unsafe_allow_html=True)

    sidebar_ui()

    mode = st.session_state.mode
    show_code = mode in [LEARNING_MODES[1], LEARNING_MODES[2], LEARNING_MODES[3]]
    code_editable = mode in [LEARNING_MODES[2], LEARNING_MODES[3]]

    if mode == LEARNING_MODES[3]:
        col_code, col_canvas = st.columns([2, 3], gap="large")
    elif show_code:
        col_canvas, col_code = st.columns([4, 1], gap="large")
    else:
        col_canvas = st.container()
        col_code = None

    with col_canvas:
        st.subheader("🧩 Etkileşimli Tuval")
        toolbar_ui()
        st.caption("Düğüm veya bağlantı seçin, sağ panelden düzenleyin.")

        layout_dir = DIRECTION_TO_LAYOUT.get(st.session_state.direction, "down")
        layout = TreeLayout(direction=layout_dir)

        normalize_state(st.session_state.flow_state)
        previous_graph_hash = graph_hash(st.session_state.flow_state)

        st.session_state.flow_state = streamlit_flow(
            key="visual_flow",
            state=st.session_state.flow_state,
            layout=layout,
            fit_view=True,
            height=820 if show_code else 920,
            allow_new_edges=True,
            enable_node_menu=True,
            enable_edge_menu=True,
            enable_pane_menu=True,
        )
        
        # KRİTİK FIX: streamlit-flow'dan dönen node'ların type'ını düzelt
        for node in st.session_state.flow_state.nodes:
            # Gerçek tipi data'dan al
            real_type = (node.data or {}).get("node_type", "default")
            # streamlit-flow sadece default/input/output kabul ediyor
            # Tüm node'lar için type="default" yap
            if hasattr(node, "type"):
                node.type = "default"
            if hasattr(node, "node_type"):
                node.node_type = "default"
        
        normalize_state(st.session_state.flow_state)
        update_selected_from_state(st.session_state.flow_state)
        current_graph_hash = graph_hash(st.session_state.flow_state)

        graph_changed = current_graph_hash != previous_graph_hash
        if not graph_changed and st.session_state.get("ignore_next_graph_change"):
            st.session_state.ignore_next_graph_change = False

        if graph_changed and st.session_state.last_edit_source != "code":
            st.session_state.last_edit_source = "graph"
            sync_code_text(generate_mermaid(
                st.session_state.flow_state,
                st.session_state.direction,
            ))
            st.session_state.last_graph_hash = current_graph_hash
            if not st.session_state.get("ignore_next_graph_change"):
                st.session_state.history_manager.push(
                    st.session_state.code_text,
                    st.session_state.flow_state,
                    "graph_change"
                )
            else:
                st.session_state.ignore_next_graph_change = False
            st.session_state.last_edit_source = None

    if show_code and col_code is not None:
        with col_code:
            st.subheader("?? Mermaid Kodu")

            code_input = st.text_area(
                "Mermaid Kodu",
                value=st.session_state.code_text,
                height=200,
                key="code_editor",
                disabled=not code_editable,
                help="Kod değişiklikleri otomatik olarak tuvale yansır.",
                label_visibility="collapsed",
            )

            code_hash = hash(code_input)
            if code_editable and code_hash != st.session_state.last_code_hash:
                st.session_state.code_text = code_input
                if st.session_state.last_edit_source != "graph":
                    parsed_state, error, direction = parse_mermaid(code_input)
                    if error:
                        st.error(error)
                    else:
                        st.session_state.last_edit_source = "code"
                        normalize_state(parsed_state)
                        st.session_state.flow_state = parsed_state
                        st.session_state.direction = direction
                        st.session_state.last_graph_hash = graph_hash(parsed_state)
                        st.session_state.last_code_hash = code_hash
                        st.session_state.last_edit_source = None

            st.divider()
            with st.expander(
                "🧰 Bağlantı ve Özellikler",
                expanded=bool(st.session_state.get("selected_node_id") or st.session_state.get("selected_edge_id")),
            ):
                edge_builder()
                st.divider()
                properties_panel()

    st.divider()
    st.download_button(
        label="Kodu Kaydet (.mmd)",
        data=st.session_state.code_text,
        file_name=f"{st.session_state.project_title}.mmd",
        mime="text/plain",
        use_container_width=True,
    )


if __name__ == "__main__":
    initialize_state()
    
    # Recovery modal göster (ilk yüklemede)
    show_recovery_modal()
    
    # Auto-save kontrolü
    current_time = int(time.time())
    if current_time - st.session_state.get("last_auto_save", 0) >= AUTO_SAVE_INTERVAL:
        auto_save_to_file()
        st.session_state.last_auto_save = current_time
    
    main()
