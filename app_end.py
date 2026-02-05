# -*- coding: utf-8 -*-
"""Akış Şeması uygulaması.

Hüseyin SIHAT tarafından eğitsel faaliyetler için hazırlanmıştır.

Özellikler
- Sürükle-bırak etkileşimli tuval (streamlit-flow)
- Çift yönlü senkronizasyon: Tuval <-> Mermaid kodu
- Undo/Redo geçmişi
- Şablonlar
- Proje kaydet/yükle (Mermaid .mmd)
- PNG/SVG dışa aktarma (mermaid.ink üzerinden, requests opsiyonel)

Notlar
- Bu uygulama, Mermaid "flowchart" sözdiziminin temel bir alt kümesini ayrıştırır.
- streamlit-flow component'i varsayılan olarak Node/Edge/Pan menülerini İngilizce getirir.
  Bu dosyada küçük bir JS çeviri katmanı ile arayüz metinleri Türkçeleştirilir.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import streamlit as st

# -----------------------------------------------------------------------------
# Sayfa ayarı (Streamlit'te ilk st.* çağrısı olmalı)
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Akış Şeması - © Hüseyin SIHAT",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Opsiyonel bağımlılıklar
# -----------------------------------------------------------------------------

try:
    import requests  # type: ignore
except Exception:
    requests = None

try:
    from groq import Groq  # type: ignore
except Exception:
    Groq = None

try:
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.utils import ImageReader  # type: ignore
    from reportlab.pdfgen import canvas  # type: ignore
    from reportlab.pdfbase import pdfmetrics  # type: ignore
    from reportlab.pdfbase.ttfonts import TTFont  # type: ignore
except Exception:
    canvas = None
    pdfmetrics = None
    TTFont = None

try:
    from streamlit_flow import streamlit_flow  # type: ignore
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode  # type: ignore
    from streamlit_flow.layouts import TreeLayout, ManualLayout  # type: ignore
    from streamlit_flow.state import StreamlitFlowState  # type: ignore
except Exception as exc:  # pragma: no cover
    st.error(
        "`streamlit-flow-component` bulunamadı veya yüklenemedi.\n\n"
        "Kurulum: `pip install streamlit-flow-component`\n\n"
        f"Hata: {exc}"
    )
    st.stop()


# =============================================================================
# Sabitler & Şablonlar
# =============================================================================

APP_CAPTION = "Hüseyin Sıhat tarafından eğitsel faaliyetler için hazırlanmıştır."

APP_TITLE = "Akış Şeması"

DEFAULT_DIRECTION = "TD"  # TD, LR, RL, BT
DEFAULT_MODE = "Basit"
DEFAULT_LAYOUT_MODE = "Otomatik (Ağaç)"
DEFAULT_EXPORT_FORMAT = "PNG"
DEFAULT_GLOBAL_NODE_COLORS = {
    "bg": "#F1F5F9",
    "border": "#334155",
    "text": "#0F172A",
}

DEFAULT_CODE = """flowchart TD
    start([Başla])
""".strip()

TEMPLATES: Dict[str, Dict[str, str]] = {
    "Boş (Başla → Bitir)": {
        "description": "En basit başlangıç",
        "code": """flowchart TD
    start([Başla]) --> end([Bitir])
""".strip(),
    },
    "Boş Proje": {
        "description": "Temiz bir başlangıç",
        "code": """flowchart TD
    S([Başlangıç])
""".strip(),
    },
    "Diş Fırçalama": {
        "description": "Günlük rutin örneği",
        "code": """flowchart TD
    s([Başla])
    io1[/Diş Fırçası Al/]
    p1[Macun Sür]
    p2[Fırçala]
    d1{2 Dakika Geçti mi?}
    p3[Ağzını Çalkala]
    e([Bitir])
    
    s --> io1
    io1 --> p1
    p1 --> p2
    p2 --> d1
    d1 -->|Hayır| p2
    d1 -->|Evet| p3
    p3 --> e
""".strip(),
    },
    "Karar Yapısı": {
        "description": "Evet/Hayır dallanması",
        "code": """flowchart TD
    start([Başla]) --> d1{Koşul doğru mu?}
    d1 -->|Evet| p1[İşlem 1]
    d1 -->|Hayır| p2[İşlem 2]
    p1 --> end([Bitir])
    p2 --> end([Bitir])
""".strip(),
    },
    "Döngü": {
        "description": "Koşullu tekrar",
        "code": """flowchart TD
    start([Başla]) --> p1[Hazırlık]
    p1 --> d1{Devam edilsin mi?}
    d1 -->|Evet| p2[Adım]
    p2 --> d1
    d1 -->|Hayır| end([Bitir])
""".strip(),
    },
    "Sabah Rutini": {
        "description": "Günlük rutin akışı",
        "code": """flowchart TD
    S([Uyan])
    A[/Alarmı kapat/]
    F[Diş fırçala]
    K{Kahve hazır mı?}
    D[Demle]
    I[İç]
    E([Gün başladı])
    S --> A --> F --> K
    K -->|Evet| I --> E
    K -->|Hayır| D --> I
""".strip(),
    },
    "ATM Para Çekme": {
        "description": "ATM adımları",
        "code": """flowchart TD
    S([Başla])
    C[/Kart tak/]
    P[/Şifre gir/]
    D{Şifre doğru mu?}
    M[İşlem seç]
    B{Bakiye yeterli mi?}
    U[Uyarı göster]
    V[Parayı ver]
    E([Bitir])
    S --> C --> P --> D
    D -->|Hayır| P
    D -->|Evet| M --> B
    B -->|Hayır| U --> E
    B -->|Evet| V --> E
""".strip(),
    },
    "Online Sipariş": {
        "description": "E-ticaret akışı",
        "code": """flowchart TD
    S([Başla])
    A[/Ürün ara/]
    B[Sepete ekle]
    C{Stok var mı?}
    D[/Adres gir/]
    E[/Ödeme yap/]
    F[(Siparişi kaydet)]
    G([Tamamlandı])
    S --> A --> B --> C
    C -->|Hayır| A
    C -->|Evet| D --> E --> F --> G
""".strip(),
    },
    "Kargo Teslimi": {
        "description": "Teslimat süreci",
        "code": """flowchart TD
    S([Başlangıç])
    A[/Adres doğrula/]
    B{Evde mi?}
    C[İmza al]
    D[[Not bırak]]
    E([Teslim])
    S --> A --> B
    B -->|Evet| C --> E
    B -->|Hayır| D --> E
""".strip(),
    },
    "Randevu Sistemi": {
        "description": "Randevu planlama",
        "code": """flowchart TD
    S([Başla])
    A[/Kimlik bilgisi al/]
    B{Slot uygun mu?}
    C[/Tarih seç/]
    D[(Randevu kaydet)]
    E([Bitir])
    S --> A --> B
    B -->|Hayır| C --> B
    B -->|Evet| D --> E
""".strip(),
    },
    "Mutfak Tarifi": {
        "description": "Yemek hazırlama",
        "code": """flowchart TD
    S([Başla])
    A[/Malzemeleri hazırla/]
    B[Karıştır]
    C{Kıvam iyi mi?}
    D[Servis et]
    E([Bitti])
    S --> A --> B --> C
    C -->|Hayır| B
    C -->|Evet| D --> E
""".strip(),
    },
    "Sınav Kayıt": {
        "description": "Kayıt süreci",
        "code": """flowchart TD
    S([Başla])
    A[/Form doldur/]
    B{Belgeler tam mı?}
    C[(Başvuruyu kaydet)]
    D([Tamam])
    S --> A --> B
    B -->|Hayır| A
    B -->|Evet| C --> D
""".strip(),
    },
    "Depo Stok": {
        "description": "Stok kontrol akışı",
        "code": """flowchart TD
    S([Başla])
    A[/Ürün girişi/]
    B[(Stok güncelle)]
    C{Minimum altı mı?}
    D[[Tedarik uyarısı]]
    E([Bitir])
    S --> A --> B --> C
    C -->|Evet| D --> E
    C -->|Hayır| E
""".strip(),
    },
    "Kütüphane Ödünç": {
        "description": "Ödünç alma süreci",
        "code": """flowchart TD
    S([Başla])
    A[/Üye kartı al/]
    B{Kitap mevcut mu?}
    C[Rezervasyon oluştur]
    D[Ödünç ver]
    K[(Kayıt oluştur)]
    E([Bitir])
    S --> A --> B
    B -->|Hayır| C --> E
    B -->|Evet| D --> K --> E
""".strip(),
    },
}

# =============================================================================
# Auto-Save (dosya sistemi)
# =============================================================================

AUTOSAVE_DIR = Path(".streamlit/autosave")
AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
AUTOSAVE_FILE = AUTOSAVE_DIR / "project_autosave.json"
AUTO_SAVE_INTERVAL = 30  # saniye

DIRECTION_LABELS = {
    "Yukarıdan Aşağı (TD)": "TD",
    "Soldan Sağa (LR)": "LR",
    "Sağdan Sola (RL)": "RL",
    "Aşağıdan Yukarı (BT)": "BT",
}

DIRECTION_TO_LAYOUT = {
    "TD": "down",
    "TB": "down",
    "LR": "right",
    "RL": "left",
    "BT": "up",
}

POSITION_LABELS = {
    "Üst": "top",
    "Alt": "bottom",
    "Sol": "left",
    "Sağ": "right",
}
POSITION_LABELS_INV = {v: k for k, v in POSITION_LABELS.items()}

EDGE_STYLE_OPTIONS = {
    "🟢 Yumuşak": {"type": "smoothstep", "variant": "solid"},
    "⚫ Düz": {"type": "straight", "variant": "solid"},
    "🟧 Basamak": {"type": "step", "variant": "solid"},
    "🟣 Basit Eğri": {"type": "simplebezier", "variant": "solid"},
    "⚪ Varsayılan": {"type": "default", "variant": "solid"},
    "⋯ Noktalı": {"type": "smoothstep", "variant": "dotted"},
    "⬛ Kalın": {"type": "straight", "variant": "thick"},
    "⚪ Daire Uç": {"type": "smoothstep", "variant": "circle"},
    "❌ Çarpı Uç": {"type": "smoothstep", "variant": "cross"},
}

# Bağlantı tipleri için sabit sıralama
EDGE_STYLE_ORDER: Tuple[str, ...] = tuple(EDGE_STYLE_OPTIONS.keys())

EDGE_COLOR_OPTIONS = {
    "Mavi": "#2563EB",
    "Yeşil": "#10B981",
    "Kırmızı": "#EF4444",
    "Turuncu": "#F59E0B",
    "Mor": "#7C3AED",
    "Siyah": "#0F172A",
    "Gri": "#64748B",
}

# Edge tipi seçiminde kullanılacak etiket -> reactflow type eşlemesi
EDGE_TYPE_LABELS = {k: v["type"] for k, v in EDGE_STYLE_OPTIONS.items()}

EDGE_VARIANT_TO_ARROW = {
    "solid": "-->",
    "dotted": "-.->",
    "thick": "==>",
    "circle": "--o",
    "cross": "--x",
}

ARROW_TO_EDGE_VARIANT = {v: k for k, v in EDGE_VARIANT_TO_ARROW.items()}

VIEW_MODES = {
    "Basit": {
        "show_code": False,
        "show_controls": True,
        "show_minimap": False,
        "enable_context_menus": False,
    },
    "Karma": {
        "show_code": True,
        "show_controls": True,
        "show_minimap": False,
        "enable_context_menus": True,
    },
    "Uzman": {
        "show_code": True,
        "show_controls": True,
        "show_minimap": True,
        "enable_context_menus": True,
    },
}

LAYOUT_MODES = ["Otomatik (Ağaç)", "Manuel (Elle)"]

SUGGESTED_LABELS = {
    "process": ["toplam = toplam + sayi", "sayac = sayac + 1", "ortalama = toplam / n"],
    "io": ["sayi al", "sonucu yaz"],
    "decision": ["Karar"],
}

TIPS = [
    "Başla düğümünü seç → üst paletten yeni düğüm ekle → otomatik bağlanır.",
    "Bağlantı etiketleri karar noktalarını netleştirir (Evet/Hayır).",
    "Düğüm metinlerini kısa ve net tut (2–5 kelime).",
    "Karar düğümlerinde en az iki çıkış oluştur.",
    "Akış yönünü Ayarlar sekmesinden değiştirebilirsiniz.",
    "Uzman modda sağ tık menüsü daha hızlı düzenleme sağlar.",
    "Örnek akışlardan ilham alıp kendi adımlarını ekleyebilirsiniz.",
    "PNG/SVG dışa aktarım için ölçek ayarını büyütebilirsiniz.",
    "Bağımsız düğümler modunda ok çizilmez; düğümler tipleriyle üretilir.",
    "Akış şemasında bağlantısız düğüm kalmamasına dikkat edin.",
    "Döngü düğümünü tekrar eden adımlar için kullanın.",
    "Not düğümü, açıklama ve ipuçları için idealdir.",
    "Fonksiyon düğümü, alt işlem çağrıları için uygundur.",
    "Bağlantı düğümü, uzun akışları temizler.",
    "Giriş/Çıkış düğümü kullanıcı etkileşimi içindir.",
    "Yeni şemaya geç butonu seçimi sıfırlar.",
    "Şema modunda düğümler otomatik bağlanır.",
    "Seçili düğüm varsa yeni düğüm altına eklenir.",
    "Karar etiketleri boşsa otomatik Evet/Hayır atanır.",
    "Kılavuz sekmesinde düğüm tiplerini hızlıca öğrenebilirsiniz.",
]

TASK_LIBRARY = {
    "Sayı Tek/Çift Kontrolü": {
        "problem": "Kullanıcıdan bir sayı al ve sayının tek mi çift mi olduğunu ekrana yazdır.",
        "min_nodes": {"io": 2, "decision": 1, "terminal": 2},
        "expected_labels": ["tek", "çift", "mod", "%"],
    },
    "Not Ortalaması Hesaplama": {
        "problem": "Kullanıcıdan 3 adet not al, ortalamayı hesapla ve ekrana yazdır.",
        "min_nodes": {"io": 4, "process": 1, "terminal": 2},
        "expected_labels": ["ortalama", "toplam", "not"],
    },
    "En Büyük Sayıyı Bulma": {
        "problem": "Kullanıcıdan üç sayı al ve bunların en büyüğünü bulup ekrana yazdır.",
        "min_nodes": {"io": 4, "decision": 2, "terminal": 2},
        "expected_labels": ["en büyük", "buyuk", "max"],
    },
    "Şifre Doğrulama Sistemi": {
        "problem": "Kullanıcıdan şifre iste. Şifre doğru girilene kadar tekrar sor. Doğru girişte başarılı mesajı göster.",
        "min_nodes": {"io": 1, "decision": 1, "terminal": 2},
        "expected_labels": ["şifre", "sifre", "doğru", "yanlış"],
    },
    "1'den N'e Kadar Toplam": {
        "problem": "Kullanıcıdan bir N sayısı al. 1'den N'e kadar olan sayıları topla ve sonucu yazdır.",
        "min_nodes": {"io": 2, "process": 2, "decision": 1, "terminal": 2},
        "expected_labels": ["toplam", "sayac", "n"],
    },
    "Faktöriyel Hesaplama": {
        "problem": "Kullanıcıdan pozitif bir sayı al ve faktöriyelini hesapla (N! = 1×2×3×...×N).",
        "min_nodes": {"io": 2, "process": 2, "decision": 1, "terminal": 2},
        "expected_labels": ["faktöriyel", "çarpım", "sayac"],
    },
    "Pozitif/Negatif/Sıfır Kontrolü": {
        "problem": "Kullanıcıdan bir sayı al. Sayının pozitif, negatif veya sıfır olduğunu belirle ve yazdır.",
        "min_nodes": {"io": 2, "decision": 2, "terminal": 2},
        "expected_labels": ["pozitif", "negatif", "sıfır"],
    },
    "Geçme/Kalma Durumu": {
        "problem": "Öğrencinin notunu al. 50 ve üzeri ise 'Geçti', altında ise 'Kaldı' yazdır.",
        "min_nodes": {"io": 2, "decision": 1, "terminal": 2},
        "expected_labels": ["geçti", "kaldı", "not", "50"],
    },
    "Asal Sayı Kontrolü": {
        "problem": "Kullanıcıdan bir sayı al. Bu sayının asal olup olmadığını kontrol et ve sonucu yazdır.",
        "min_nodes": {"io": 2, "process": 2, "decision": 2, "terminal": 2},
        "expected_labels": ["asal", "bölen", "mod"],
    },
    "Fibonacci Serisi": {
        "problem": "Kullanıcıdan N değeri al. İlk N adet Fibonacci sayısını hesapla ve yazdır (0,1,1,2,3,5,8...).",
        "min_nodes": {"io": 2, "process": 3, "decision": 1, "terminal": 2},
        "expected_labels": ["fibonacci", "önceki", "sonraki"],
    },
    "Basit Hesap Makinesi": {
        "problem": "İki sayı ve bir işlem (+,-,*,/) al. İşleme göre hesaplama yap ve sonucu göster.",
        "min_nodes": {"io": 3, "decision": 4, "process": 1, "terminal": 2},
        "expected_labels": ["toplama", "çıkarma", "çarpma", "bölme"],
    },
    "Yaş Kategorisi Belirleme": {
        "problem": "Kullanıcının yaşını al. 0-12 çocuk, 13-17 genç, 18-64 yetişkin, 65+ yaşlı kategorisine ayır.",
        "min_nodes": {"io": 2, "decision": 3, "terminal": 2},
        "expected_labels": ["çocuk", "genç", "yetişkin", "yaşlı"],
    },
    "Dizideki En Küçük Sayı": {
        "problem": "Kullanıcıdan 5 sayı al. Bu sayıların en küçüğünü bulup ekrana yazdır.",
        "min_nodes": {"io": 6, "process": 1, "decision": 4, "terminal": 2},
        "expected_labels": ["en küçük", "min", "karşılaştır"],
    },
    "Mükemmel Sayı Kontrolü": {
        "problem": "Bir sayı al. Sayının bölenlerinin toplamı kendisine eşitse 'Mükemmel sayı', değilse 'Değil' yazdır.",
        "min_nodes": {"io": 2, "process": 2, "decision": 2, "terminal": 2},
        "expected_labels": ["bölen", "toplam", "mükemmel"],
    },
    "Armstrong Sayısı": {
        "problem": "3 basamaklı bir sayı al. Her basamağın küplerinin toplamı sayıya eşitse 'Armstrong', değilse 'Değil'.",
        "min_nodes": {"io": 2, "process": 4, "decision": 1, "terminal": 2},
        "expected_labels": ["basamak", "küp", "armstrong"],
    },
    "Üçgen Alan Hesabı": {
        "problem": "Üçgenin taban ve yüksekliğini al. Alanı hesapla (Alan = taban × yükseklik / 2) ve yazdır.",
        "min_nodes": {"io": 3, "process": 1, "terminal": 2},
        "expected_labels": ["taban", "yükseklik", "alan"],
    },
    "Çarpım Tablosu": {
        "problem": "Kullanıcıdan bir sayı al. Bu sayının 1'den 10'a kadar çarpım tablosunu ekrana yazdır.",
        "min_nodes": {"io": 2, "process": 2, "decision": 1, "terminal": 2},
        "expected_labels": ["çarpım", "sayac", "tablo"],
    },
    "Sayı Tahmin Oyunu": {
        "problem": "1-100 arası rastgele bir sayı tut. Kullanıcı doğru tahmin edene kadar 'Büyük' veya 'Küçük' ipucu ver.",
        "min_nodes": {"io": 2, "decision": 3, "terminal": 2},
        "expected_labels": ["tahmin", "büyük", "küçük", "doğru"],
    },
    "Harfleri Sesli/Sessiz Ayırma": {
        "problem": "Kullanıcıdan bir harf al. Bu harfin sesli (a,e,i,o,u) mi sessiz mi olduğunu belirle ve yazdır.",
        "min_nodes": {"io": 2, "decision": 5, "terminal": 2},
        "expected_labels": ["sesli", "sessiz", "harf"],
    },
    "Banka Hesap İşlemi": {
        "problem": "Başlangıç bakiyesi al. Kullanıcıdan işlem seç (yatır/çek). Geçerli işlem yap, yetersiz bakiyede uyarı ver.",
        "min_nodes": {"io": 3, "decision": 2, "process": 2, "terminal": 2},
        "expected_labels": ["bakiye", "yatır", "çek", "işlem"],
    },
}

# Uygulama düzeyinde basit bir "node türleri" kütüphanesi.
# streamlit-flow kendi node_type alanında sadece default/input/output bekler.
# Biz kendi "kind" alanımızı node.data içine koyup stilimizi inline style ile veriyoruz.
NODE_KIND = {
    "terminal": {
        "label": "Başla/Bitir",
        "icon": "⏺️",
        "default": "Başla",
        "bg": "#ECFDF5",
        "border": "#10B981",
        "text": "#065F46",
        "shape": "terminal",
    },
    "process": {
        "label": "İşlem",
        "icon": "⚙️",
        "default": "İşlem",
        "bg": "#F1F5F9",
        "border": "#334155",
        "text": "#0F172A",
        "shape": "rect",
    },
    "decision": {
        "label": "Karar",
        "icon": "❓",
        "default": "Karar",
        "bg": "#FFE7A3",
        "border": "#D97706",
        "text": "#7C2D12",
        "shape": "diamond",
    },
    "io": {
        "label": "Giriş/Çıkış",
        "icon": "⌨️",
        "default": "Giriş/Çıkış",
        "bg": "#EFF6FF",
        "border": "#2563EB",
        "text": "#1E3A8A",
        "shape": "parallelogram",
    },
    "document": {
        "label": "Belge",
        "icon": "📄",
        "default": "Belge",
        "bg": "#FFF7ED",
        "border": "#F97316",
        "text": "#9A3412",
        "shape": "document",
    },
    "multi_document": {
        "label": "Çoklu Belgeler",
        "icon": "📑",
        "default": "Çoklu Belgeler",
        "bg": "#FFF7ED",
        "border": "#F97316",
        "text": "#9A3412",
        "shape": "multi_document",
    },
    "data_storage": {
        "label": "Veri Deposu",
        "icon": "🗃️",
        "default": "Veri Deposu",
        "bg": "#DCFCE7",
        "border": "#16A34A",
        "text": "#166534",
        "shape": "data_storage",
    },
    "internal_storage": {
        "label": "Dahili Depo",
        "icon": "🧠",
        "default": "Dahili Depo",
        "bg": "#DCFCE7",
        "border": "#15803D",
        "text": "#166534",
        "shape": "internal_storage",
    },
    "tape_data": {
        "label": "Bant Veri",
        "icon": "📼",
        "default": "Bant Veri",
        "bg": "#DCFCE7",
        "border": "#16A34A",
        "text": "#166534",
        "shape": "tape_data",
    },
    "subprocess": {
        "label": "Alt Süreç",
        "icon": "🧩",
        "default": "Alt Süreç",
        "bg": "#F3E8FF",
        "border": "#7C3AED",
        "text": "#5B21B6",
        "shape": "subroutine",
    },
    "database": {
        "label": "Veritabanı",
        "icon": "🗄️",
        "default": "Veritabanı",
        "bg": "#EEF2FF",
        "border": "#1E40AF",
        "text": "#1E3A8A",
        "shape": "database",
    },
    "display": {
        "label": "Görüntü",
        "icon": "🖥️",
        "default": "Görüntü",
        "bg": "#FEF3C7",
        "border": "#D97706",
        "text": "#92400E",
        "shape": "display",
    },
    "manual_operation": {
        "label": "Manuel İşlem",
        "icon": "✋",
        "default": "Manuel İşlem",
        "bg": "#FEF3C7",
        "border": "#D97706",
        "text": "#92400E",
        "shape": "manual_operation",
    },
    "merge": {
        "label": "Birleştir",
        "icon": "🔻",
        "default": "Birleştir",
        "bg": "#FEF3C7",
        "border": "#D97706",
        "text": "#92400E",
        "shape": "merge",
    },
    "manual_input": {
        "label": "Manuel Giriş",
        "icon": "✍️",
        "default": "Manuel Giriş",
        "bg": "#FEF3C7",
        "border": "#D97706",
        "text": "#92400E",
        "shape": "manual_input",
    },
    "connector": {
        "label": "Bağlantı",
        "icon": "🔗",
        "default": "Bağlantı",
        "bg": "#FFF3C4",
        "border": "#F59E0B",
        "text": "#92400E",
        "shape": "circle",
    },
    "comment": {
        "label": "Not",
        "icon": "📝",
        "default": "Açıklama",
        "bg": "#FFF7ED",
        "border": "#EA580C",
        "text": "#7C2D12",
        "shape": "note",
    },
    "loop": {
        "label": "Döngü",
        "icon": "🔁",
        "default": "Döngü",
        "bg": "#CFFAFE",
        "border": "#0891B2",
        "text": "#0C4A6E",
        "shape": "hex",
    },
    "function": {
        "label": "Fonksiyon",
        "icon": "🧠",
        "default": "Fonksiyon Çağrısı",
        "bg": "#EDE9FE",
        "border": "#6D28D9",
        "text": "#4C1D95",
        "shape": "double",
    },
}

# Düğüm türleri için sabit sıralama
NODE_KIND_ORDER: Tuple[str, ...] = tuple(NODE_KIND.keys())

def node_kind_label(kind: str) -> str:
    """Düğüm tipini Türkçe olarak döndürür."""
    spec = NODE_KIND.get(kind, NODE_KIND["process"])
    return str(spec.get("label", kind))

# AI üretiminde zorunlu tutulacak düğüm türleri (akış modu için çekirdek set)
AI_REQUIRED_BASE: Tuple[str, ...] = ("terminal", "process", "decision")
AI_EXTRA_KINDS: Tuple[str, ...] = (
    "subprocess",
    "database",
    "connector",
    "comment",
    "loop",
    "function",
)
# Konu açıkça gerektirmedikçe IO düğümü zorunlu değildir.
AI_IO_HINTS: Tuple[str, ...] = (
    "girdi",
    "çıktı",
    "cikti",
    "input",
    "output",
    "form",
    "veri",
    "dosya",
    "belge",
    "rapor",
    "liste",
)
AI_MIN_NODES_BASE = 5
AI_MIN_NODES_WITH_IO = 6

# "İşlem" gibi genel süreç etiketlerini anlamlı aksiyonlara dönüştürmek için
DEFAULT_ACTION_POOL: Tuple[str, ...] = (
    "Hazırlık Yap",
    "Bilgi Topla",
    "Kontrol Et",
    "Uygula",
    "Onayla",
    "Kaydet",
    "Güncelle",
    "Bildirim Gönder",
    "Tamamla",
)

# Bağımsız düğüm üretimi için hedef aralık
FREE_NODES_MIN = 6
FREE_NODES_MAX = 18
FREE_KIND_CYCLE: Tuple[str, ...] = (
    "terminal",
    "process",
    "io",
    "decision",
    "document",
    "multi_document",
    "display",
    "manual_input",
    "manual_operation",
    "merge",
    "data_storage",
    "internal_storage",
    "tape_data",
    "subprocess",
    "database",
    "connector",
    "comment",
    "loop",
    "function",
)

# Mermaid şekil şablonları (id ve label kullanılır)
MERMAID_NODE_TEMPLATES = {
    "terminal": "{id}([ {label} ])",  # Stadium
    "process": "{id}[{label}]",
    "io": "{id}[/ {label} /]",
    "decision": "{id}{{{label}}}",
    "document": "{id}[{label}]:::document",
    "multi_document": "{id}[{label}]:::multi_document",
    "data_storage": "{id}[( {label} )]:::data_storage",
    "internal_storage": "{id}[{label}]:::internal_storage",
    "tape_data": "{id}[{label}]:::tape_data",
    "display": "{id}[{label}]:::display",
    "manual_operation": "{id}[{label}]:::manual_operation",
    "merge": "{id}[{label}]:::merge",
    "manual_input": "{id}[/ {label} /]:::manual_input",
    "subprocess": "{id}[[{label}]]",
    "database": "{id}[( {label} )]",
    "connector": "{id}(({label}))",
    "comment": "{id}[{label}]:::comment",
    "loop": "{id}{{{label}}}:::loop",
    "function": "{id}[[{label}]]:::function",
}

EXPORT_NODE_TEMPLATES = {
    "terminal": "{id}([ {label} ])",
    "process": "{id}[{label}]",
    "io": "{id}[/ {label} /]",
    "decision": "{id}{{{label}}}",
    "document": "{id}[{label}]",
    "multi_document": "{id}[{label}]",
    "data_storage": "{id}[( {label} )]",
    "internal_storage": "{id}[{label}]",
    "tape_data": "{id}[{label}]",
    "display": "{id}[{label}]",
    "manual_operation": "{id}[{label}]",
    "merge": "{id}[{label}]",
    "manual_input": "{id}[/ {label} /]",
    "subprocess": "{id}[[{label}]]",
    "database": "{id}[( {label} )]",
    "connector": "{id}(({label}))",
    "comment": "{id}[{label}]",
    "loop": "{id}{{{label}}}",
    "function": "{id}[[{label}]]",
}

USER_MODES = {
    "Basit": {
        "show_code": False,
        "show_controls": True,
        "show_minimap": False,
        "enable_context_menus": False,
        "show_templates": False,
        "allow_edge_style": True,
        "export_formats": ["PNG"],
        "palette": ["terminal", "process", "decision", "io"],
    },
    "Uzman": {
        "show_code": True,
        "show_controls": True,
        "show_minimap": True,
        "enable_context_menus": True,
        "show_templates": False,
        "allow_edge_style": True,
        "export_formats": ["Mermaid", "PNG", "SVG", "JSON", "PDF"],
        "palette": list(NODE_KIND.keys()),
    },
}

USER_MODE_DETAILS = {
    "Basit": [
        "Sadece tuval ve temel düğümler görünür.",
        "Yeni başlayanlar için sade akış oluşturma.",
        "Sadece PNG dışa aktarım.",
    ],
    "Uzman": [
        "Mini harita ve sağ tık menüleri.",
        "Gelişmiş düzen/bağlantı kontrolleri.",
        "Geniş ekran ve yoğun çalışma için ideal.",
    ],
}


# =============================================================================
# Geçmiş (Undo/Redo)
# =============================================================================

@dataclass
class HistoryEntry:
    """Tek bir geri-al/ileri-al kaydı."""

    code_text: str
    node_snapshot: List[dict] = field(default_factory=list)
    edge_snapshot: List[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    action: str = "edit"


class HistoryManager:
    """Basit undo/redo yöneticisi."""

    MAX_HISTORY = 25

    def __init__(self) -> None:
        self.undo_stack: List[HistoryEntry] = []
        self.redo_stack: List[HistoryEntry] = []

    def push(self, code_text: str, flow_state: StreamlitFlowState, action: str = "edit") -> None:
        nodes = serialize_nodes(flow_state.nodes)
        edges = serialize_edges(flow_state.edges)
        entry = HistoryEntry(
            code_text=code_text,
            node_snapshot=nodes,
            edge_snapshot=edges,
            timestamp=time.time(),
            action=action,
        )
        self.undo_stack.append(entry)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.MAX_HISTORY:
            self.undo_stack.pop(0)

    def can_undo(self) -> bool:
        return len(self.undo_stack) >= 2

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def undo(self) -> Optional[HistoryEntry]:
        if len(self.undo_stack) < 2:
            return None
        current = self.undo_stack.pop()
        self.redo_stack.append(current)
        return self.undo_stack[-1]

    def redo(self) -> Optional[HistoryEntry]:
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        self.undo_stack.append(entry)
        return entry


# =============================================================================
# Yardımcılar
# =============================================================================


def safe_int(v: object, default: int) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except Exception:
        return default


def get_node_pos(node: StreamlitFlowNode) -> Tuple[float, float]:
    """Node konumunu (x,y) olarak alır (pos veya position uyumlu)."""
    if hasattr(node, "pos") and node.pos is not None:
        try:
            x, y = node.pos  # type: ignore[misc]
            return float(x), float(y)
        except Exception:
            pass
    if hasattr(node, "position") and node.position is not None:
        pos = node.position  # type: ignore[attr-defined]
        if isinstance(pos, dict):
            return float(pos.get("x", 0)), float(pos.get("y", 0))
        try:
            x, y = pos  # type: ignore[misc]
            return float(x), float(y)
        except Exception:
            pass
    return 0.0, 0.0


def set_node_pos(node: StreamlitFlowNode, pos: Tuple[float, float]) -> None:
    if hasattr(node, "pos"):
        node.pos = pos  # type: ignore[attr-defined]
    if hasattr(node, "position"):
        node.position = {"x": pos[0], "y": pos[1]}  # type: ignore[attr-defined]


def snap_to_grid(x: float, y: float, grid_size: int = 20) -> Tuple[float, float]:
    """Koordinatları ızgaraya hizalar (Grid Snap).
    
    Args:
        x: X koordinatı
        y: Y koordinatı
        grid_size: Izgara boyutu (piksel)
    
    Returns:
        Hizalanmış (x, y) koordinatları
    
    Example:
        >>> snap_to_grid(127, 83, 20)
        (120.0, 80.0)
    """
    return (round(x / grid_size) * grid_size, round(y / grid_size) * grid_size)


def get_node_label(node: StreamlitFlowNode) -> str:
    data = getattr(node, "data", None) or {}
    # Biz label'ı data içinde saklıyoruz.
    label = data.get("label") or ""
    if not label:
        content = data.get("content")
        if isinstance(content, str):
            # markdown içinden basit çıkarım: **ICON Label**
            label = re.sub(r"\*\*", "", content).strip()
    return str(label)


def get_node_kind(node: StreamlitFlowNode) -> str:
    data = getattr(node, "data", None) or {}
    return str(data.get("kind") or "process")


def parse_style_width(style: object, fallback: int = 160) -> int:
    if not isinstance(style, dict):
        return fallback
    w = style.get("width")
    if w is None:
        return fallback
    if isinstance(w, (int, float)):
        return int(w)
    if isinstance(w, str):
        m = re.search(r"(\d+)", w)
        if m:
            return int(m.group(1))
    return fallback


def get_edge_label(edge: StreamlitFlowEdge) -> str:
    lbl = getattr(edge, "label", "")
    return str(lbl or "")


def get_edge_type(edge: StreamlitFlowEdge) -> str:
    # Edge sınıfı edge_type paramı alıyor ama ReactFlow 'type' kullanıyor.
    v = getattr(edge, "edge_type", None)
    if v:
        return str(v)
    v = getattr(edge, "type", None)
    if v:
        return str(v)
    return "default"


def get_edge_variant(edge: StreamlitFlowEdge) -> str:
    """Edge görsel varyantını döndürür (solid/dotted/thick/circle/cross)."""
    data = getattr(edge, "data", None) or {}
    variant = data.get("variant")
    if variant:
        return str(variant)
    if hasattr(edge, "variant"):
        v = getattr(edge, "variant")
        if v:
            return str(v)
    return "solid"


def serialize_nodes(nodes: List[StreamlitFlowNode]) -> List[dict]:
    out: List[dict] = []
    for n in nodes:
        style = getattr(n, "style", {}) or {}
        data = getattr(n, "data", None) or {}
        colors = normalize_color_overrides(data.get("colors") if isinstance(data, dict) else None)
        out.append(
            {
                "id": n.id,
                "pos": [get_node_pos(n)[0], get_node_pos(n)[1]],
                "label": get_node_label(n),
                "kind": get_node_kind(n),
                "node_type": getattr(n, "node_type", "default"),
                "source_position": getattr(n, "source_position", "bottom"),
                "target_position": getattr(n, "target_position", "top"),
                "width": parse_style_width(style, fallback=160),
            }
        )
        if colors:
            out[-1]["colors"] = colors
    return out


def serialize_edges(edges: List[StreamlitFlowEdge]) -> List[dict]:
    out: List[dict] = []
    for e in edges:
        out.append(
            {
                "id": e.id,
                "source": e.source,
                "target": e.target,
                "label": get_edge_label(e),
                "edge_type": get_edge_type(e),
                "variant": get_edge_variant(e),
                "color": get_edge_color(e),
            }
        )
    return out


def build_state_from_snapshot(node_snapshot: List[dict], edge_snapshot: List[dict]) -> StreamlitFlowState:
    nodes: List[StreamlitFlowNode] = []
    edges: List[StreamlitFlowEdge] = []

    for nd in node_snapshot:
        nid = str(nd.get("id"))
        kind = str(nd.get("kind") or "process")
        label = str(nd.get("label") or nid)
        pos_list = nd.get("pos") or [0, 0]
        pos = (float(pos_list[0]), float(pos_list[1]))
        width = safe_int(nd.get("width"), 160)
        colors = normalize_color_overrides(nd.get("colors") if isinstance(nd.get("colors"), dict) else None)

        nodes.append(
            make_node(
                node_id=nid,
                label=label,
                kind=kind,
                pos=pos,
                width=width,
                source_position=str(nd.get("source_position") or "bottom"),
                target_position=str(nd.get("target_position") or "top"),
                colors=colors,
            )
        )

    for ed in edge_snapshot:
        eid = str(ed.get("id"))
        src = str(ed.get("source"))
        tgt = str(ed.get("target"))
        lbl = str(ed.get("label") or "")
        etype = str(ed.get("edge_type") or "smoothstep")
        variant = str(ed.get("variant") or "solid")
        color = ed.get("color") if isinstance(ed.get("color"), str) else None
        edges.append(make_edge(eid, src, tgt, lbl, etype, variant, color=color))

    return make_flow_state(nodes, edges)


def build_state_from_history(entry: HistoryEntry) -> StreamlitFlowState:
    return build_state_from_snapshot(entry.node_snapshot, entry.edge_snapshot)


def graph_hash(flow_state: StreamlitFlowState) -> str:
    payload = {
        "nodes": serialize_nodes(flow_state.nodes),
        "edges": serialize_edges(flow_state.edges),
        "direction": st.session_state.get("direction", DEFAULT_DIRECTION),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def text_hash(text: str) -> str:
    """Metin için stabil hash üretir."""
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def build_edge_id(source: str, target: str, label: str, variant: str, salt: str = "") -> str:
    """Deterministik edge id üretir."""
    base = f"{source}|{target}|{label}|{variant}|{salt}"
    hid = hashlib.md5(base.encode("utf-8")).hexdigest()[:8]
    return f"e_{hid}_{source}_{target}"


def sync_code_text(new_code: str) -> None:
    st.session_state.code_text = new_code
    st.session_state.last_code_hash = text_hash(new_code)


def refresh_code_from_state() -> str:
    """Flow state'ten güncel Mermaid kodunu üretip state'e yazar."""
    normalize_state(st.session_state.flow_state)
    code = generate_mermaid(st.session_state.flow_state, st.session_state.direction)
    sync_code_text(code)
    return code


def build_export_code() -> str:
    """Dışa aktarma için sadeleştirilmiş Mermaid kodu üretir."""
    normalize_state(st.session_state.flow_state)
    return generate_mermaid_for_export(st.session_state.flow_state, st.session_state.direction)


def build_minimal_export_code() -> str:
    """Dışa aktarma hatasında en güvenli Mermaid kodunu üretir."""
    normalize_state(st.session_state.flow_state)
    direction = (st.session_state.direction or DEFAULT_DIRECTION).upper()
    if direction not in {"TD", "TB", "LR", "RL", "BT"}:
        direction = "TD"
    nodes_sorted = sorted(st.session_state.flow_state.nodes, key=lambda x: x.id)
    id_map = {n.id: f"n{i + 1}" for i, n in enumerate(nodes_sorted)}
    lines = [f"flowchart {direction}"]
    for i, n in enumerate(nodes_sorted, start=1):
        safe_id = id_map.get(n.id, n.id)
        lines.append(f"    {safe_id}[Node {i}]")
    for e in sorted(st.session_state.flow_state.edges, key=lambda x: (x.source, x.target, x.id)):
        src = id_map.get(e.source, e.source)
        tgt = id_map.get(e.target, e.target)
        lines.append(f"    {src} --> {tgt}")
    return "\n".join(lines)


def toast_success(message: str) -> None:
    """Başarı mesajı gösterir."""
    st.toast(f"✅ {message}")


def toast_warning(message: str) -> None:
    """Uyarı mesajı gösterir."""
    st.toast(f"⚠️ {message}")


def toast_error(message: str) -> None:
    """Hata mesajı gösterir."""
    st.toast(f"❌ {message}")


def toast_info(message: str) -> None:
    """Bilgi mesajı gösterir."""
    st.toast(f"ℹ️ {message}")


def safe_filename(name: str, suffix: str) -> str:
    name = name.strip() or "akis_semasi"
    name = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü _\-]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return f"{name}{suffix}"


def suggest_label_for_kind(kind: str) -> str:
    """Node türüne göre hızlı etiket önerisi döndür."""
    if kind not in SUGGESTED_LABELS:
        return NODE_KIND.get(kind, NODE_KIND["process"])["default"]
    suggestions = SUGGESTED_LABELS[kind]
    idx_map = st.session_state.get("label_suggestion_index") or {}
    idx = int(idx_map.get(kind, 0))
    label = suggestions[idx % len(suggestions)]
    idx_map[kind] = idx + 1
    st.session_state.label_suggestion_index = idx_map
    return label


def auto_save_to_file() -> None:
    try:
        save_data = {
            "code_text": st.session_state.code_text,
            "direction": st.session_state.direction,
            "project_title": st.session_state.project_title,
            "user_mode": st.session_state.user_mode,
            "view_mode": st.session_state.view_mode,
            "show_code": st.session_state.show_code,
            "show_controls": st.session_state.show_controls,
            "show_minimap": st.session_state.show_minimap,
            "ai_mode": st.session_state.ai_mode,
            "groq_api_key": st.session_state.groq_api_key,
            "show_grid": st.session_state.show_grid,
            "enable_context_menus": st.session_state.enable_context_menus,
            "auto_connect": st.session_state.auto_connect,
            "node_spacing": st.session_state.node_spacing,
            "layout_mode": st.session_state.layout_mode,
            "export_format": st.session_state.export_format,
            "export_scale": st.session_state.export_scale,
            "auto_validate": st.session_state.auto_validate,
            "selected_task": st.session_state.selected_task,
            "show_rubric": st.session_state.show_rubric,
            "show_pseudocode": st.session_state.show_pseudocode,
            "global_node_colors_enabled": st.session_state.get("global_node_colors_enabled", False),
            "global_node_bg": st.session_state.get("global_node_bg"),
            "global_node_border": st.session_state.get("global_node_border"),
            "global_node_text": st.session_state.get("global_node_text"),
            "timestamp": int(time.time()),
        }
        AUTOSAVE_FILE.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        toast_warning(f"Auto-save hatası: {exc}")


def load_autosave() -> Optional[Dict]:
    if not AUTOSAVE_FILE.exists():
        return None
    try:
        return json.loads(AUTOSAVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def maybe_auto_save() -> None:
    now = int(time.time())
    last = int(st.session_state.get("last_auto_save", 0) or 0)
    if now - last >= AUTO_SAVE_INTERVAL:
        auto_save_to_file()
        st.session_state.last_auto_save = now


def sync_counters_from_state(flow_state: StreamlitFlowState) -> None:
    max_node = 1
    for n in flow_state.nodes:
        m = re.match(r"^n(\d+)$", n.id)
        if m:
            max_node = max(max_node, int(m.group(1)))
    max_edge = 1
    for e in flow_state.edges:
        m = re.match(r"^e(\d+)_", e.id)
        if m:
            max_edge = max(max_edge, int(m.group(1)))
    st.session_state.node_counter = max_node
    st.session_state.edge_counter = max_edge


def show_recovery_banner() -> None:
    autosave = load_autosave()
    if not autosave or st.session_state.get("recovery_shown"):
        return

    st.session_state.recovery_shown = True
    ts = int(autosave.get("timestamp", time.time()))
    ts_str = time.strftime("%H:%M:%S", time.localtime(ts))

    with st.container():
        st.warning(f"📂 Kaydedilmemiş proje bulundu ({ts_str})")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("♻️ Geri Yükle", key="recover_yes", use_container_width=True):
                code_text = str(autosave.get("code_text") or "")
                parsed_state, error, direction = parse_mermaid(code_text)
                if parsed_state is None or error:
                    code_text = DEFAULT_CODE
                    parsed_state, _, direction = parse_mermaid(code_text)

                st.session_state.code_text = code_text
                st.session_state.direction = str(autosave.get("direction") or direction or DEFAULT_DIRECTION)
                st.session_state.project_title = str(autosave.get("project_title") or st.session_state.project_title)
                st.session_state.user_mode = str(autosave.get("user_mode") or st.session_state.user_mode)
                st.session_state.view_mode = str(autosave.get("view_mode") or st.session_state.view_mode)
                st.session_state.show_code = bool(autosave.get("show_code", st.session_state.show_code))
                st.session_state.show_controls = bool(autosave.get("show_controls", st.session_state.show_controls))
                st.session_state.show_minimap = bool(autosave.get("show_minimap", st.session_state.show_minimap))
                st.session_state.ai_mode = str(autosave.get("ai_mode") or st.session_state.ai_mode)
                saved_key = autosave.get("groq_api_key")
                if saved_key:
                    st.session_state.groq_api_key = str(saved_key)
                st.session_state.show_grid = bool(autosave.get("show_grid", st.session_state.show_grid))
                st.session_state.enable_context_menus = bool(
                    autosave.get("enable_context_menus", st.session_state.enable_context_menus)
                )
                st.session_state.auto_connect = bool(autosave.get("auto_connect", st.session_state.auto_connect))
                st.session_state.node_spacing = int(autosave.get("node_spacing", st.session_state.node_spacing))
                st.session_state.layout_mode = str(autosave.get("layout_mode") or st.session_state.layout_mode)
                st.session_state.export_format = str(autosave.get("export_format") or st.session_state.export_format)
                st.session_state.export_scale = int(autosave.get("export_scale") or st.session_state.export_scale)
                st.session_state.auto_validate = bool(autosave.get("auto_validate", st.session_state.auto_validate))
                st.session_state.selected_task = str(autosave.get("selected_task") or st.session_state.selected_task)
                st.session_state.show_rubric = bool(autosave.get("show_rubric", st.session_state.show_rubric))
                st.session_state.show_pseudocode = bool(
                    autosave.get("show_pseudocode", st.session_state.show_pseudocode)
                )
                st.session_state.global_node_colors_enabled = bool(
                    autosave.get("global_node_colors_enabled", st.session_state.global_node_colors_enabled)
                )
                st.session_state.global_node_bg = str(
                    autosave.get("global_node_bg") or st.session_state.global_node_bg
                )
                st.session_state.global_node_border = str(
                    autosave.get("global_node_border") or st.session_state.global_node_border
                )
                st.session_state.global_node_text = str(
                    autosave.get("global_node_text") or st.session_state.global_node_text
                )

                if st.session_state.ai_mode == "Şema (Oklu)":
                    st.session_state.ai_mode = "Akış Şeması"
                elif st.session_state.ai_mode == "Serbest (Bağımsız)":
                    st.session_state.ai_mode = "Bağımsız Düğümler"

                st.session_state.flow_state = parsed_state  # type: ignore[assignment]
                normalize_state(st.session_state.flow_state)
                sync_counters_from_state(st.session_state.flow_state)

                st.session_state.history = HistoryManager()
                st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="recovery")
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                st.session_state.last_code_hash = text_hash(st.session_state.code_text)
                toast_success("Proje geri yüklendi")
                st.rerun()
        with col2:
            if st.button("🗑️ Yeni Başla", key="recover_no", use_container_width=True):
                AUTOSAVE_FILE.unlink(missing_ok=True)
                st.rerun()


# =============================================================================
# AI (Groq) Fonksiyonu
# =============================================================================

def generate_flow_with_ai(prompt: str, api_key: str, model: str = "llama-3.3-70b-versatile") -> Optional[str]:
    """Groq kullanarak metin açıklamasından Mermaid kodu üretir.
    
    Args:
        prompt: Kullanıcının akış tanımı
        api_key: Groq API anahtarı
        model: Kullanılacak AI modeli
    """
    if Groq is None:
        st.error("Groq kütüphanesi yüklü değil. Lütfen `pip install groq` komutunu çalıştırın.")
        return None
    
    if not api_key:
        st.warning("Lütfen bir Groq API Anahtarı girin.")
        return None

    client = Groq(api_key=api_key)
    
    system_prompt = """Sen profesyonel bir akış şeması uzmanısın. Kullanıcının verdiği konuya uygun, SADE, NET ve ekranı kalabalıklaştırmayan bir akış şeması oluştur.

KRİTİK KURALLAR:

1. DÜĞÜM YAPISI:
   - ÖNCE tüm düğümleri tanımla (her düğüm ayrı satırda)
   - Sonra boş satır bırak
   - Son olarak bağlantıları yaz
   - HER DÜĞÜM MUTLAKA bir bağlantıya sahip olmalı (bağlantısız düğüm YASAK!)

2. DÜĞÜM TİPLERİ - Doğru Şekil Kullan:
   - Varsayılan olarak Terminal, İşlem ve Karar kullan.
   - Giriş/Çıkış (IO) sadece konu açıkça gerektiriyorsa kullan.
   - Alt süreç, veritabanı, bağlantı, not, döngü, fonksiyon gibi türleri ancak gerçekten gerekliyse kullan.
   
   Terminal (Başla/Bitir): ([...])
   s([Başla: Okula Gidiş])
   e([Bitir: Derste])
   
   İşlem (Eylem/İş): [...]
   p1[Kahvaltı Yap]
   p2[Çantayı Hazırla]
   
   Karar (Koşul/Soru): {...}
   d1{Servis Var mı?}
   
   Giriş/Çıkış: [/...../]
   io1[/Bilgi Al/]
   
   Alt Süreç: [[...]]
   sp1[[Duş Al ve Giyin]]

   Veritabanı: [(...)]
   db1[(Öğrenci Kaydı)]
   
   Bağlantı: ((...))
   c1((Sayfa Bağlantısı))

   Not: [...]:::comment
   n1[Not: Kontrol Noktası]:::comment

   Döngü: {...}:::loop
   loop1{Tekrar Gerekli mi?}:::loop

   Fonksiyon: [[...]]:::function
   fn1[[Fonksiyon Çağır]]:::function

3. ETİKET KURALLARI:
   - Doğal, anlaşılır Türkçe
   - İngilizce etiket KULLANMA (Start/End/Yes/No gibi)
   - 2-5 kelime arası (gerekirse 6)
   - p1, d1, io1 gibi KODLAR ETİKETTE GÖRÜNMESİN
   - Konuya özel, gerçekçi adımlar
   - ASLA "İşlem" etiketi kullanma; her işlem fiil + nesne içermeli (örn: "Kahvaltı Yap")
   - "Adım", "Kontrol", "Uygula" gibi GENEL etiketler kullanma
   - Her etiket benzersiz olmalı (tekrar etme)
   - Karar etiketleri soru şeklinde bitmeli (… mı/mi?)

4. BAĞLANTILAR:
   - Normal ok: -->
   - Karar dalları: -->|Evet| ve -->|Hayır|
   - Döngü: -->|Tekrar| veya -->|Devam|
   - Dalları kısa tut ve tekrar birleşsin
   - Gereksiz çapraz bağlantı yapma; akışı sıralı ve okunur tut
   - Karar dışındaki bağlantılara etiket yazma
   - "Yes/No" KULLANMA, yalnızca "Evet/Hayır" kullan

5. DÜĞÜM SAYISI - SADELEŞTİR:
   - Basit konular: 5-7 düğüm
   - Orta konular: 7-9 düğüm
   - Karmaşık konular: 9-11 düğüm
   - En fazla 2 karar; çoğu durumda 1 karar yeterli
   - Mikro adımları birleştir, aynı amaca hizmet eden ardışık adımları tek süreçte topla

6. İYİ AKIŞ ŞEMASININ ÖZELLİKLERİ:
   - Başlangıç ve bitiş açık olmalı
   - Tüm olası durumlar kapsamalı
   - Gerçekçi ve mantıklı adımlar
   - Görsel düzen sade ve örneklerdeki gibi hizalı olmalı (üstten alta, minimum çapraz)

ÖRNEK 1 - OKULA GİDİŞ (7 DÜĞÜM):
flowchart TD
    s([Başla: Okula Gidiş])
    p1[Uyan ve Hazırlan]
    p2[Kahvaltı Yap]
    d1{Servis Var mı?}
    p3[Servise Bin]
    p4[Yürüyerek Git]
    e([Bitir: Sınıfta])
    
    s --> p1
    p1 --> p2
    p2 --> d1
    d1 -->|Evet| p3
    d1 -->|Hayır| p4
    p3 --> e
    p4 --> e

ÖRNEK 2 - ALIŞVERİŞ YAPMA (8 DÜĞÜM):
flowchart TD
    s([Başla: Alışveriş])
    p1[Liste Hazırla]
    p2[Markete Git]
    p3[Ürünleri Seç]
    d1{Liste Tamamlandı mı?}
    p4[Kasaya Git]
    p5[Ödeme Yap]
    e([Bitir: Eve Dön])
    
    s --> p1
    p1 --> p2
    p2 --> p3
    p3 --> d1
    d1 -->|Hayır| p3
    d1 -->|Evet| p4
    p4 --> p5
    p5 --> e

ÖNEMLİ:
- flowchart TD ile başla
- ```mermaid KULLANMA, sadece düz kod
- Tüm düğümler bağlı olmalı
- Konuya uygun, SADE şema oluştur
- Örnekler format içindir; kendi üretiminde konuya uygun düğüm tiplerini kullan
"""

    def is_rate_limit_error(msg: str) -> bool:
        text = (msg or "").lower()
        if "rate_limit_exceeded" in text or "rate limit reached" in text:
            return True
        if "error code: 429" in text or "status code 429" in text or " http 429" in text:
            return True
        return False

    try:
        with st.spinner("🤖 AI akış şemasını düşünüyor..."):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Şu konuda akış şeması oluştur: {prompt}"}
                ],
                temperature=0.2, 
                max_tokens=1500,
            )
            content = response.choices[0].message.content.strip()
            # Markdown temizliği
            content = content.replace("```mermaid", "").replace("```", "").strip()
            st.session_state.ai_last_error = ""
            return content

    except Exception as e:
        msg = str(e)
        if is_rate_limit_error(msg):
            m = re.search(r"in\\s+(\\d+)m(\\d+(?:\\.\\d+)?)s", msg)
            if m:
                mins = int(m.group(1))
                secs = float(m.group(2))
                wait_sec = int(mins * 60 + secs)
                st.session_state.ai_rate_limit_until = int(time.time()) + wait_sec
            st.session_state.ai_last_error = "rate_limit"
            st.warning("⚠️ AI isteği sınır aşıldı! Lütfen biraz bekleyip tekrar deneyin.")
        else:
            st.session_state.ai_last_error = "error"
            st.error(f"❌ AI Hatası: {e}")
        return None


def generate_free_nodes_with_ai(
    prompt: str,
    api_key: str,
    model: str = "llama-3.3-70b-versatile",
) -> Optional[List[Dict[str, str]]]:
    """Groq ile bağımsız düğüm listesi üretir (label + kind)."""
    if Groq is None:
        st.error("Groq kütüphanesi yüklü değil. Lütfen `pip install groq` komutunu çalıştırın.")
        return None
    if not api_key:
        st.warning("Lütfen bir Groq API Anahtarı girin.")
        return None

    client = Groq(api_key=api_key)
    system_prompt = """
Sen bir akış şeması içerik yazarı ve bilgi tasarımcısın.
GÖREV: Verilen konu için BAĞIMSIZ düğüm listesi üret (ok yok).
Akış şeması moduyla UYUMLU olsun; aynı ana adımlar yer alsın.

KURALLAR:
- Düğüm sayısını konuya göre kendin seç: 6 ile 18 arası
- Etiketler doğal ve anlamlı Türkçe olmalı
- İngilizce etiket KULLANMA
- 2-6 kelime arası, fiil + nesne tercih et
- p1, d1, io1 gibi kısaltmalar KULLANMA
- "kind" alanı sadece şu değerlerden biri olmalı:
  terminal, process, io, decision, subprocess, database, connector, comment, loop, function
- Düğüm tipleri çeşitlensin ama konuya uymayan türleri zorla ekleme
- Sadece JSON dizi döndür:
  [{"label": "Etiket 1", "kind": "process"}, ...]
- Markdown, açıklama, numara, ekstra metin KULLANMA
"""
    def parse_labels_fallback(text: str) -> List[str]:
        cleaned = text.replace("•", "\n").replace("-", "\n")
        parts = re.split(r"[\n,;]+", cleaned)
        out: List[str] = []
        for p in parts:
            p = re.sub(r"^\s*\d+[\).\-\s]+", "", p).strip()
            if p:
                out.append(p)
        return out

    def is_rate_limit_error(msg: str) -> bool:
        text = (msg or "").lower()
        if "rate_limit_exceeded" in text or "rate limit reached" in text:
            return True
        if "error code: 429" in text or "status code 429" in text or " http 429" in text:
            return True
        return False

    try:
        with st.spinner("🤖 AI bağımsız kutuları düşünüyor..."):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Konu: {prompt}"}
                ],
                temperature=0.3,
                max_tokens=500,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            try:
                payload = json.loads(raw)
                if isinstance(payload, list):
                    kind_cycle = list(FREE_KIND_CYCLE)
                    out: List[Dict[str, str]] = []
                    for idx, item in enumerate(payload):
                        if isinstance(item, dict):
                            label = str(item.get("label", "")).strip()
                            kind = str(item.get("kind", "")).strip()
                        else:
                            label = str(item).strip()
                            kind = kind_cycle[idx % len(kind_cycle)]
                        if label:
                            if kind not in NODE_KIND:
                                kind = "process"
                            out.append({"label": label, "kind": kind})
                    if len(out) >= FREE_NODES_MIN:
                        st.session_state.ai_last_error = ""
                        return out
            except Exception:
                pass
            fallback = parse_labels_fallback(raw)
            if len(fallback) >= 6:
                st.session_state.ai_last_error = ""
                kind_cycle = list(FREE_KIND_CYCLE)
                return [
                    {"label": lbl, "kind": kind_cycle[idx % len(kind_cycle)]}
                    for idx, lbl in enumerate(fallback)
                ]
            return None
    except Exception as e:
        msg = str(e)
        if is_rate_limit_error(msg):
            m = re.search(r"in\\s+(\\d+)m(\\d+(?:\\.\\d+)?)s", msg)
            if m:
                mins = int(m.group(1))
                secs = float(m.group(2))
                wait_sec = int(mins * 60 + secs)
                st.session_state.ai_rate_limit_until = int(time.time()) + wait_sec
            st.session_state.ai_last_error = "rate_limit"
            st.warning("⚠️ AI isteği sınır aşıldı! Lütfen biraz bekleyip tekrar deneyin.")
        else:
            st.session_state.ai_last_error = "error"
            st.error(f"❌ AI Hatası: {e}")
        return None


def fallback_free_labels(topic: str, count: int = 9) -> List[str]:
    base = turkish_title((topic or "Adım").strip() or "Adım")
    return [f"{base} - Adım {i + 1}" for i in range(count)]


# =============================================================================
# streamlit-flow nesne üretimi (node/edge/state)
# =============================================================================


def make_flow_state(nodes: List[StreamlitFlowNode], edges: List[StreamlitFlowEdge]) -> StreamlitFlowState:
    """StreamlitFlowState yaratır (farklı sürüm imzalarına karşı toleranslı)."""
    try:
        return StreamlitFlowState(nodes=nodes, edges=edges)
    except TypeError:
        # Bazı sürümlerde positional bekleniyor olabilir
        return StreamlitFlowState(nodes, edges)  # type: ignore[call-arg]


def node_markdown(label: str, kind: str) -> str:
    icon = NODE_KIND.get(kind, NODE_KIND["process"]).get("icon", "")
    # Markdown node bileşenlerinde bold çalışır.
    return f"**{icon} {label}**".strip()

def normalize_color_overrides(colors: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not isinstance(colors, dict):
        return {}
    out: Dict[str, str] = {}
    for key in ("bg", "border", "text"):
        val = colors.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def get_global_node_colors() -> Dict[str, str]:
    if not st.session_state.get("global_node_colors_enabled"):
        return {}
    colors = {
        "bg": st.session_state.get("global_node_bg"),
        "border": st.session_state.get("global_node_border"),
        "text": st.session_state.get("global_node_text"),
    }
    return normalize_color_overrides(colors)


def node_style(kind: str, width: int = 160, colors: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    spec = NODE_KIND.get(kind, NODE_KIND["process"])
    colors = normalize_color_overrides(colors)
    bg = colors.get("bg") or spec["bg"]
    border = colors.get("border") or spec["border"]
    text = colors.get("text") or spec["text"]
    use_custom = bool(colors)

    base: Dict[str, object] = {
        "backgroundColor": bg,
        "border": f"2px solid {border}",
        "color": text,
        "fontWeight": 900,
        "padding": "10px 12px",
        "width": f"{int(width)}px",
        "boxShadow": "0 6px 18px rgba(15, 23, 42, 0.08)",
    }

    def apply_clip(path_value: str) -> None:
        base["clipPath"] = path_value
        base["WebkitClipPath"] = path_value

    shape = spec.get("shape")
    if shape == "terminal":
        base["borderRadius"] = "999px"
    elif shape == "diamond":
        # Elmas görünümü: clip-path (metin dönmez)
        apply_clip("polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)")
        base["padding"] = "18px 14px"
        base["boxShadow"] = f"0 0 0 2px {border} inset, 0 6px 18px rgba(15, 23, 42, 0.12)"
    elif shape == "parallelogram":
        apply_clip("polygon(8% 0%, 100% 0%, 92% 100%, 0% 100%)")
    elif shape == "subroutine":
        base["borderStyle"] = "solid"
        base["borderRadius"] = "10px"
        base["background"] = (
            f"linear-gradient(90deg, {border} 0, {border} 4px, {bg} 4px, "
            f"{bg} calc(100% - 4px), {border} calc(100% - 4px), {border} 100%)"
        )
    elif shape == "database":
        base["borderRadius"] = "18px"
        if not use_custom:
            base["background"] = "linear-gradient(180deg, rgba(238,242,255,1) 0%, rgba(224,231,255,1) 100%)"
    elif shape == "circle":
        base["borderRadius"] = "999px"
        base["width"] = f"{max(90, int(width))}px"
    elif shape == "note":
        base["border"] = f"2px dashed {border}"
        base["borderStyle"] = "dashed"
        base["borderWidth"] = "2px"
        base["borderRadius"] = "10px"
        if not use_custom:
            base["background"] = "linear-gradient(180deg, rgba(255,247,237,1) 0%, rgba(255,237,213,1) 100%)"
    elif shape == "hex":
        apply_clip("polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%)")
        base["padding"] = "18px 14px"
        base["boxShadow"] = f"0 0 0 2px {border} inset, 0 6px 18px rgba(15, 23, 42, 0.12)"
    elif shape == "double":
        base["borderStyle"] = "double"
        base["borderWidth"] = "4px"
        base["borderRadius"] = "12px"
    elif shape == "document":
        apply_clip(
            "polygon(0% 0%, 100% 0%, 100% 82%, 85% 92%, 70% 82%, 50% 92%, 30% 82%, 15% 92%, 0% 82%)"
        )
        base["padding"] = "16px 14px 20px"
    elif shape == "multi_document":
        apply_clip(
            "polygon(0% 0%, 100% 0%, 100% 82%, 85% 92%, 70% 82%, 50% 92%, 30% 82%, 15% 92%, 0% 82%)"
        )
        base["padding"] = "16px 14px 20px"
        base["boxShadow"] = (
            f"6px 6px 0 -2px {border}, 12px 12px 0 -4px {border}, "
            "0 6px 18px rgba(15, 23, 42, 0.08)"
        )
    elif shape == "data_storage":
        apply_clip("polygon(8% 0%, 92% 0%, 100% 50%, 92% 100%, 8% 100%, 0% 50%)")
        base["padding"] = "16px 14px"
    elif shape == "internal_storage":
        base["borderRadius"] = "10px"
        base["background"] = (
            f"linear-gradient(90deg, {border} 0, {border} 4px, {bg} 4px, "
            f"{bg} calc(100% - 4px), {border} calc(100% - 4px), {border} 100%)"
        )
    elif shape == "tape_data":
        base["borderRadius"] = "999px"
        base["width"] = f"{max(120, int(width))}px"
        base["padding"] = "16px 14px"
    elif shape == "display":
        apply_clip("polygon(0% 0%, 88% 0%, 100% 50%, 88% 100%, 0% 100%)")
        base["padding"] = "16px 14px"
    elif shape == "manual_operation":
        apply_clip("polygon(0% 0%, 100% 0%, 90% 100%, 10% 100%)")
        base["padding"] = "16px 14px"
    elif shape == "merge":
        apply_clip("polygon(0% 0%, 100% 0%, 50% 100%)")
        base["padding"] = "18px 14px 20px"
    elif shape == "manual_input":
        apply_clip("polygon(0% 15%, 100% 0%, 100% 100%, 0% 100%)")
        base["padding"] = "16px 14px"
    else:
        base["borderRadius"] = "12px"

    return base


def default_handle_positions(direction: str) -> Tuple[str, str]:
    direction = (direction or DEFAULT_DIRECTION).upper()
    if direction == "LR":
        return "right", "left"
    if direction == "RL":
        return "left", "right"
    if direction == "BT":
        return "top", "bottom"
    return "bottom", "top"


def edge_style_for_type(
    edge_type: str, variant: str = "solid", color_override: Optional[str] = None
) -> Tuple[Dict[str, object], Dict[str, str]]:
    color_map = {
        "smoothstep": "#1f2937",
        "straight": "#0f172a",
        "step": "#b45309",
        "simplebezier": "#6d28d9",
        "default": "#334155",
    }
    color = color_override or color_map.get(edge_type, "#1f2937")
    style: Dict[str, object] = {"strokeWidth": 2.6, "stroke": color}
    marker = {"type": "arrowclosed", "color": color}

    if variant == "dotted":
        style["strokeDasharray"] = "4 6"
    elif variant == "thick":
        style["strokeWidth"] = 4.2
    elif variant == "circle":
        marker = {"type": "arrow", "color": color}
        style["strokeDasharray"] = "2 4"
    elif variant == "cross":
        style["strokeDasharray"] = "10 4 2 4"

    return style, marker


def get_edge_color(edge: StreamlitFlowEdge) -> Optional[str]:
    data = getattr(edge, "data", None) or {}
    color = data.get("color")
    if isinstance(color, str) and color.strip():
        return color
    return None


def edge_color_label(color: Optional[str]) -> str:
    if not color:
        return "Otomatik (türe göre)"
    for label, value in EDGE_COLOR_OPTIONS.items():
        if value == color:
            return label
    return "Otomatik (türe göre)"


def edge_style_label(edge_type: str, variant: str) -> str:
    """Edge türü ve varyantına göre kullanıcı etiketini döndürür."""
    for label, spec in EDGE_STYLE_OPTIONS.items():
        if spec["type"] == edge_type and spec["variant"] == variant:
            return label
    return "🟢 Yumuşak"


def make_node(
    node_id: str,
    label: str,
    kind: str,
    pos: Tuple[float, float] = (0.0, 0.0),
    width: int = 160,
    source_position: Optional[str] = None,
    target_position: Optional[str] = None,
    colors: Optional[Dict[str, str]] = None,
) -> StreamlitFlowNode:
    if not source_position or not target_position:
        src, tgt = default_handle_positions(st.session_state.get("direction", DEFAULT_DIRECTION))
        source_position = source_position or src
        target_position = target_position or tgt
    data = {
        "content": node_markdown(label, kind),
        "label": label,
        "kind": kind,
    }
    color_overrides = normalize_color_overrides(colors)
    if color_overrides:
        data["colors"] = color_overrides

    return StreamlitFlowNode(
        id=node_id,
        pos=pos,
        data=data,
        node_type="default",
        source_position=source_position,
        target_position=target_position,
        draggable=True,
        selectable=True,
        connectable=True,
        deletable=True,
        style=node_style(kind, width=width, colors=color_overrides),
    )


def make_edge(
    edge_id: str,
    source: str,
    target: str,
    label: str = "",
    edge_type: str = "smoothstep",
    variant: str = "solid",
    color: Optional[str] = None,
) -> StreamlitFlowEdge:
    style, marker = edge_style_for_type(edge_type, variant, color_override=color)
    data = {"variant": variant}
    if color:
        data["color"] = color
    return StreamlitFlowEdge(
        id=edge_id,
        source=source,
        target=target,
        edge_type=edge_type,
        label=label or "",
        label_show_bg=True,
        deletable=True,
        animated=False,
        marker_end=marker,
        style=style,
        data=data,
    )


def normalize_state(flow_state: StreamlitFlowState) -> None:
    """State içindeki node/edge'leri bizim veri alanlarımızla uyumlu hale getir."""
    # Node'larda data/content/kind yoksa tamamla
    default_src, default_tgt = default_handle_positions(st.session_state.get("direction", DEFAULT_DIRECTION))
    selected_node_id = st.session_state.get("selected_node_id")
    selected_edge_id = st.session_state.get("selected_edge_id")
    enable_grid_snap = st.session_state.get("enable_grid_snap", False)
    
    for n in flow_state.nodes:
        if getattr(n, "data", None) is None:
            n.data = {}  # type: ignore[attr-defined]
        data = n.data or {}
        kind = str(data.get("kind") or "process")
        label = str(data.get("label") or data.get("content") or n.id)
        data["kind"] = kind
        data["label"] = label
        data["content"] = node_markdown(label, kind)
        color_overrides = normalize_color_overrides(data.get("colors") if isinstance(data, dict) else None)
        if color_overrides:
            data["colors"] = color_overrides
        else:
            data.pop("colors", None)
        n.data = data  # type: ignore[attr-defined]
        
        # Grid snap (eğer aktifse)
        if enable_grid_snap:
            pos = get_node_pos(n)
            snapped_pos = snap_to_grid(pos[0], pos[1], grid_size=20)
            set_node_pos(n, snapped_pos)

        # style: tip/renk/şekil bazlı yeniden üret
        existing_style = getattr(n, "style", {}) or {}
        width = parse_style_width(existing_style, fallback=160)
        global_colors = get_global_node_colors()
        effective_colors = global_colors if global_colors else color_overrides
        style = node_style(kind, width=width, colors=effective_colors)

        # Seçili düğüm border efekti
        is_selected = (n.id == selected_node_id)
        if is_selected:
            base_shadow = style.get("boxShadow")
            highlight = "0 0 0 4px rgba(59, 130, 246, 0.2), 0 8px 16px rgba(0,0,0,0.12)"
            style["border"] = "3px dashed #3B82F6"
            if base_shadow:
                style["boxShadow"] = f"{base_shadow}, {highlight}"
            else:
                style["boxShadow"] = highlight

        n.style = style  # type: ignore[attr-defined]

        # node_type streamlit-flow'un beklediği değerlerden biri olmalı
        if hasattr(n, "node_type"):
            if getattr(n, "node_type") not in {"default", "input", "output"}:
                n.node_type = "default"  # type: ignore[attr-defined]

        if hasattr(n, "source_position"):
            if not getattr(n, "source_position", None):
                n.source_position = default_src  # type: ignore[attr-defined]
        if hasattr(n, "target_position"):
            if not getattr(n, "target_position", None):
                n.target_position = default_tgt  # type: ignore[attr-defined]

    for e in flow_state.edges:
        if getattr(e, "label", None) is None:
            e.label = ""  # type: ignore[attr-defined]
        etype = get_edge_type(e)
        variant = get_edge_variant(e)
        color_override = get_edge_color(e)
        style, marker = edge_style_for_type(etype, variant, color_override=color_override)
        
        # Seçili bağlantı vurgusu
        is_selected_edge = (e.id == selected_edge_id)
        if is_selected_edge:
            style["stroke"] = "#3B82F6"
            style["strokeWidth"] = 4
            style["strokeDasharray"] = "8 4"
        
        e.style = style  # type: ignore[attr-defined]
        e.marker_end = marker  # type: ignore[attr-defined]
        if getattr(e, "data", None) is None:
            e.data = {}  # type: ignore[attr-defined]
        e.data["variant"] = variant  # type: ignore[attr-defined]


# =============================================================================
# Mermaid <-> State dönüşümü
# =============================================================================

FLOW_HEADER_RE = re.compile(r"^\s*(?:flowchart|graph)\s+(TD|TB|LR|RL|BT)\s*$", re.IGNORECASE)

# Basit edge desenleri (kendi ürettiğimiz sözdizimini hedefler)
EDGE_WITH_PIPE_LABEL_RE = re.compile(
    r"^\s*(?P<src>.+?)\s*(?P<arrow>-->|-\.->|==>|--o|--x|<-->)\s*\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<dst>.+?)\s*$"
)
EDGE_SIMPLE_RE = re.compile(
    r"^\s*(?P<src>.+?)\s*(?P<arrow>-->|-\.->|==>|--o|--x|<-->)\s*(?P<dst>.+?)\s*$"
)


def split_node_token(token: str) -> Tuple[str, str, str]:
    """Mermaid düğüm ifadesini (id, label, kind) olarak çözer.

    Desteklenen örnekler:
    - id[Metin] (process)
    - id([Metin]) (terminal)
    - id{Metin} (decision)
    - id[/Metin/] (io)
    - id[[Metin]] (subprocess)
    - id[(Metin)] (database)
    - id((Metin)) (connector)

    Geri dönüş: (id, label, kind)
    """

    s = token.strip()

    kind_override: Optional[str] = None
    m_class = re.search(r":::(?P<kind>[A-Za-z0-9_\-]+)\s*$", s)
    if m_class:
        kind_override = m_class.group("kind")
        s = s[: m_class.start()].strip()

    # Önce id'yi al: id + kalan
    # id kısmı: ilk boşluğa kadar (veya şekil başlangıcına kadar)
    # Bizim ürettiğimiz id'ler boşluk içermez.

    # Terminal: id([label])
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\(\[\s*(?P<label>.*?)\s*\]\)\s*$", s)
    if m:
        kind = "terminal"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Connector: id((label))
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\(\(\s*(?P<label>.*?)\s*\)\)\s*$", s)
    if m:
        kind = "connector"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Subprocess: id[[label]]
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\[\[\s*(?P<label>.*?)\s*\]\]\s*$", s)
    if m:
        kind = "subprocess"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Database: id[(label)]
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\[\(\s*(?P<label>.*?)\s*\)\]\s*$", s)
    if m:
        kind = "database"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # IO: id[/label/]
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\[/\s*(?P<label>.*?)\s*/\]\s*$", s)
    if m:
        kind = "io"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Decision: id{label}
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\{\s*(?P<label>.*?)\s*\}\s*$", s)
    if m:
        kind = "decision"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Process: id[label]
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\[\s*(?P<label>.*?)\s*\]\s*$", s)
    if m:
        kind = "process"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Rounded: id(label) -> process
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*\(\s*(?P<label>.*?)\s*\)\s*$", s)
    if m:
        kind = "process"
        if kind_override in NODE_KIND:
            kind = kind_override
        return m.group("id"), m.group("label"), kind

    # Sadece id
    m = re.match(r"^(?P<id>[A-Za-z0-9_\-]+)\s*$", s)
    if m:
        nid = m.group("id")
        kind = "process"
        if kind_override in NODE_KIND:
            kind = kind_override
        return nid, nid, kind

    # Fallback: boşluklu/karmaşık id'leri de yakalamaya çalış
    parts = s.split()
    nid = parts[0]
    kind = "process"
    if kind_override in NODE_KIND:
        kind = kind_override
    return nid, " ".join(parts[1:]) if len(parts) > 1 else nid, kind


def parse_mermaid(code_text: str) -> Tuple[Optional[StreamlitFlowState], Optional[str], str]:
    """Mermaid (flowchart) kodunu parse eder.

    Geri dönüş: (state, error, direction)
    
    Args:
        code_text: Mermaid flowchart kodu
    
    Returns:
        Tuple[state, error, direction]:
            - state: Başarılıysa StreamlitFlowState, değilse None
            - error: Hata mesajı varsa string, yoksa None
            - direction: Akış yönü ("TD", "LR", vb.)
    """

    if not code_text or not code_text.strip():
        return None, "⚠️ **Boş Kod:** Lütfen Mermaid kodu girin.", st.session_state.get("direction", DEFAULT_DIRECTION)

    # Satır satır temizle
    lines: List[str] = []
    direction = st.session_state.get("direction", DEFAULT_DIRECTION)
    for raw in code_text.splitlines():
        # Mermaid yorumları: %% ...
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%%"):
            continue
        # header
        m = FLOW_HEADER_RE.match(line)
        if m:
            direction = m.group(1).upper()
            continue
        lines.append(line)

    nodes: Dict[str, Dict[str, str]] = {}
    edges: List[Tuple[str, str, str, str]] = []  # src, dst, label, variant
    alias_map: Dict[Tuple[str, str, str], str] = {}

    def resolve_node_id(nid: str, label: str, kind: str) -> str:
        key = (nid, label, kind)
        if key in alias_map:
            return alias_map[key]
        if nid not in nodes:
            alias_map[key] = nid
            return nid
        # Aynı id farklı içerik ile gelirse yeni id üret
        idx = 2
        while f"{nid}_{idx}" in nodes:
            idx += 1
        new_id = f"{nid}_{idx}"
        alias_map[key] = new_id
        return new_id

    def upsert_node(nid: str, label: str, kind: str) -> None:
        if nid not in nodes:
            nodes[nid] = {"label": label, "kind": kind}
            return
        # var olanı bozma; ama label boş ise güncelle
        if not nodes[nid].get("label") and label:
            nodes[nid]["label"] = label
        # kind boşsa güncelle
        if not nodes[nid].get("kind") and kind:
            nodes[nid]["kind"] = kind

    for line in lines:
        # Edge - etiketli
        m = EDGE_WITH_PIPE_LABEL_RE.match(line)
        if m:
            src_token = m.group("src").strip()
            dst_token = m.group("dst").strip()
            lbl = m.group("label").strip()
            arrow = m.group("arrow")
            src_id_raw, src_label, src_kind = split_node_token(src_token)
            dst_id_raw, dst_label, dst_kind = split_node_token(dst_token)
            src_id = resolve_node_id(src_id_raw, src_label, src_kind)
            dst_id = resolve_node_id(dst_id_raw, dst_label, dst_kind)
            upsert_node(src_id, src_label, src_kind)
            upsert_node(dst_id, dst_label, dst_kind)
            variant = ARROW_TO_EDGE_VARIANT.get(arrow, "solid")
            if arrow == "<-->":
                edges.append((src_id, dst_id, lbl, variant))
                edges.append((dst_id, src_id, lbl, variant))
            else:
                edges.append((src_id, dst_id, lbl, variant))
            continue

        m = EDGE_SIMPLE_RE.match(line)
        if m:
            src_token = m.group("src").strip()
            dst_token = m.group("dst").strip()
            arrow = m.group("arrow")
            src_id_raw, src_label, src_kind = split_node_token(src_token)
            dst_id_raw, dst_label, dst_kind = split_node_token(dst_token)
            src_id = resolve_node_id(src_id_raw, src_label, src_kind)
            dst_id = resolve_node_id(dst_id_raw, dst_label, dst_kind)
            upsert_node(src_id, src_label, src_kind)
            upsert_node(dst_id, dst_label, dst_kind)
            variant = ARROW_TO_EDGE_VARIANT.get(arrow, "solid")
            if arrow == "<-->":
                edges.append((src_id, dst_id, "", variant))
                edges.append((dst_id, src_id, "", variant))
            else:
                edges.append((src_id, dst_id, "", variant))
            continue

        # Node tanımı tek satır
        # ör: A[Metin]
        try:
            nid_raw, lbl, kind = split_node_token(line)
            nid = resolve_node_id(nid_raw, lbl, kind)
            upsert_node(nid, lbl, kind)
        except Exception:
            # görmezden gel
            pass

    if not nodes:
        return None, (
            "Mermaid içinden düğüm bulunamadı. (Desteklenen: `A[Metin]`, `B{Karar}`, "
            "`A --> B`, `A -->|Evet| B`)"
        ), direction

    # Node listesi
    flow_nodes: List[StreamlitFlowNode] = []
    # Basit konumlandırma (layout engine de zaten düzeltecek)
    x0, y0 = 0.0, 0.0
    step_x, step_y = 220.0, 120.0
    for i, (nid, info) in enumerate(sorted(nodes.items(), key=lambda kv: kv[0])):
        lbl = info.get("label") or nid
        kind = info.get("kind") or "process"
        pos = (x0 + (i % 3) * step_x, y0 + (i // 3) * step_y)
        flow_nodes.append(make_node(nid, lbl, kind, pos=pos))

    # Edge listesi
    flow_edges: List[StreamlitFlowEdge] = []
    seen_ids: Dict[str, int] = {}
    for src, dst, lbl, variant in sorted(edges, key=lambda x: (x[0], x[1], x[2], x[3])):
        base_id = build_edge_id(src, dst, lbl, variant)
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            eid = build_edge_id(src, dst, lbl, variant, salt=str(seen_ids[base_id]))
        else:
            seen_ids[base_id] = 1
            eid = base_id
        edge_type = "straight" if variant == "thick" else "smoothstep"
        flow_edges.append(make_edge(eid, src, dst, lbl, edge_type=edge_type, variant=variant))

    state = make_flow_state(flow_nodes, flow_edges)
    normalize_state(state)
    return state, None, direction


def mermaid_escape_label(label: str) -> str:
    # Mermaid etiketlerinde yeni satır ve kapatma karakterleri sorun çıkarabilir.
    # Türkçe karakterlerle sorun yok; sadece satır sonlarını temizleyelim.
    s = (label or "").replace("\n", " ").replace("\r", " ")
    s = s.replace("|", "/")
    s = re.sub(r"[\[\]\(\)\{\}]", "", s)
    s = re.sub(r"(-->|==>|-\\.->|--o|--x)", "→", s)
    s = s.replace("->", "→").replace("<-", "←")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def sanitize_export_label(label: str, fallback: str = "") -> str:
    """Dışa aktarma için daha agresif etiket temizliği."""
    s = (label or "").replace("\n", " ").replace("\r", " ").strip()
    s = s.replace("|", "/")
    s = re.sub(r"[\[\]\(\)\{\}<>]", "", s)
    s = re.sub(r"(-->|==>|-\\.->|--o|--x|<-->|->|<-)", "", s)
    s = s.replace("→", "").replace("←", "")
    s = re.sub(r"[`\"']", "", s)
    s = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü\\s.,;:!?+*/=%-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s and fallback:
        return fallback
    return s


def _tr_upper_char(ch: str) -> str:
    table = {
        "i": "İ",
        "ı": "I",
        "ş": "Ş",
        "ğ": "Ğ",
        "ü": "Ü",
        "ö": "Ö",
        "ç": "Ç",
    }
    return table.get(ch, ch.upper())


def _tr_lower_char(ch: str) -> str:
    table = {
        "İ": "i",
        "I": "ı",
        "Ş": "ş",
        "Ğ": "ğ",
        "Ü": "ü",
        "Ö": "ö",
        "Ç": "ç",
    }
    return table.get(ch, ch.lower())


def turkish_title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    words = re.split(r"(\s+)", text)
    out = []
    for w in words:
        if w.isspace():
            out.append(w)
            continue
        if not w:
            continue
        first = _tr_upper_char(w[0])
        rest = "".join(_tr_lower_char(c) for c in w[1:])
        out.append(first + rest)
    return "".join(out)


def node_to_mermaid(n: StreamlitFlowNode) -> str:
    nid = n.id
    label = mermaid_escape_label(get_node_label(n) or nid)
    kind = get_node_kind(n)
    tpl = MERMAID_NODE_TEMPLATES.get(kind, MERMAID_NODE_TEMPLATES["process"])
    return tpl.format(id=nid, label=label)


def node_to_mermaid_export(n: StreamlitFlowNode) -> str:
    nid = n.id
    label = mermaid_escape_label(get_node_label(n) or nid)
    kind = get_node_kind(n)
    tpl = EXPORT_NODE_TEMPLATES.get(kind, EXPORT_NODE_TEMPLATES["process"])
    return tpl.format(id=nid, label=label)


def generate_mermaid(flow_state: StreamlitFlowState, direction: str) -> str:
    direction = (direction or DEFAULT_DIRECTION).upper()
    lines: List[str] = [f"flowchart {direction}"]

    # Düğümleri sabit sırada yaz
    for n in sorted(flow_state.nodes, key=lambda x: x.id):
        lines.append(f"    {node_to_mermaid(n)}")

    # Bağlantılar
    for e in sorted(flow_state.edges, key=lambda x: (x.source, x.target, x.id)):
        lbl = mermaid_escape_label(get_edge_label(e))
        variant = get_edge_variant(e)
        arrow = EDGE_VARIANT_TO_ARROW.get(variant, "-->")
        if lbl:
            lines.append(f"    {e.source} {arrow}|{lbl}| {e.target}")
        else:
            lines.append(f"    {e.source} {arrow} {e.target}")

    return "\n".join(lines)


def generate_mermaid_for_export(flow_state: StreamlitFlowState, direction: str) -> str:
    direction = (direction or DEFAULT_DIRECTION).upper()
    if direction not in {"TD", "TB", "LR", "RL", "BT"}:
        direction = "TD"
    lines: List[str] = [f"flowchart {direction}"]

    nodes_sorted = sorted(flow_state.nodes, key=lambda x: x.id)
    id_map = {n.id: f"n{i + 1}" for i, n in enumerate(nodes_sorted)}

    for n in nodes_sorted:
        safe_id = id_map.get(n.id, n.id)
        label = sanitize_export_label(get_node_label(n) or safe_id, fallback=safe_id)
        kind = get_node_kind(n)
        tpl = EXPORT_NODE_TEMPLATES.get(kind, EXPORT_NODE_TEMPLATES["process"])
        lines.append(f"    {tpl.format(id=safe_id, label=label)}")

    for e in sorted(flow_state.edges, key=lambda x: (x.source, x.target, x.id)):
        src = id_map.get(e.source, e.source)
        tgt = id_map.get(e.target, e.target)
        lbl = sanitize_export_label(get_edge_label(e))
        variant = get_edge_variant(e)
        arrow = EDGE_VARIANT_TO_ARROW.get(variant, "-->")
        if lbl:
            lines.append(f"    {src} {arrow}|{lbl}| {tgt}")
        else:
            lines.append(f"    {src} {arrow} {tgt}")

    return "\n".join(lines)


# =============================================================================
# Doğrulama / Analiz
# =============================================================================


@dataclass
class ValidationItem:
    level: str  # "info" | "warning" | "error"
    message: str


def is_start_node(node: StreamlitFlowNode) -> bool:
    """Başlangıç düğümü olup olmadığını heuristik olarak belirler."""
    label = get_node_label(node).lower()
    if get_node_kind(node) != "terminal":
        return False
    return any(k in label for k in ["başla", "basla", "start", "giriş", "giris"])


def is_end_node(node: StreamlitFlowNode) -> bool:
    """Bitiş düğümü olup olmadığını heuristik olarak belirler."""
    label = get_node_label(node).lower()
    if get_node_kind(node) != "terminal":
        return False
    return any(k in label for k in ["bitir", "son", "end", "çıkış", "cikis"])


def build_graph(flow_state: StreamlitFlowState) -> Tuple[Dict[str, List[StreamlitFlowEdge]], Dict[str, List[StreamlitFlowEdge]]]:
    """Graph için adjacency list üretir."""
    out_edges: Dict[str, List[StreamlitFlowEdge]] = defaultdict(list)
    in_edges: Dict[str, List[StreamlitFlowEdge]] = defaultdict(list)
    for e in flow_state.edges:
        out_edges[e.source].append(e)
        in_edges[e.target].append(e)
    return out_edges, in_edges


def enforce_connected_flow(flow_state: StreamlitFlowState) -> None:
    """Akış şemasında bağlantısız (bağımsız) düğüm kalmamasını sağlar."""
    nodes = flow_state.nodes
    edges = flow_state.edges
    if not nodes or len(nodes) == 1:
        return

    # Hiç edge yoksa, düğümleri sırayla bağla
    if not edges:
        new_edges: List[StreamlitFlowEdge] = []
        for i in range(len(nodes) - 1):
            src = nodes[i].id
            tgt = nodes[i + 1].id
            eid = build_edge_id(src, tgt, "", "solid", salt=str(i))
            new_edges.append(make_edge(eid, src, tgt, label="", edge_type="smoothstep"))
        flow_state.edges = new_edges
        return

    out_edges, in_edges = build_graph(flow_state)
    start_nodes = [n for n in nodes if is_start_node(n)]
    if start_nodes:
        roots = start_nodes
    else:
        roots = [n for n in nodes if len(in_edges.get(n.id, [])) == 0]
        if not roots:
            roots = [nodes[0]]

    reachable: set[str] = set()
    q = deque([n.id for n in roots])
    while q:
        nid = q.popleft()
        if nid in reachable:
            continue
        reachable.add(nid)
        for e in out_edges.get(nid, []):
            q.append(e.target)

    if len(reachable) < len(nodes):
        # Bağımsız düğümleri düşürmek yerine zincire bağla
        out_edges, _ = build_graph(flow_state)
        dead_ends = [n for n in nodes if n.id in reachable and len(out_edges.get(n.id, [])) == 0]
        tail = dead_ends[-1].id if dead_ends else nodes[0].id
        for idx, n in enumerate([n for n in nodes if n.id not in reachable], start=1):
            if n.id == tail:
                continue
            eid = build_edge_id(tail, n.id, "", "solid", salt=f"fix{idx}")
            edges.append(make_edge(eid, tail, n.id, label="", edge_type="smoothstep"))
            tail = n.id
        flow_state.edges = edges


def polish_ai_labels(flow_state: StreamlitFlowState, topic: str = "") -> None:
    """AI etiketlerini daha doğal hale getirir."""
    base = turkish_title((topic or "").strip())
    phrase_map = [
        ("sign up", "Kayıt Ol"),
        ("sign in", "Giriş Yap"),
        ("log in", "Giriş Yap"),
        ("log out", "Çıkış Yap"),
        ("login page", "Giriş Sayfası"),
        ("registration page", "Kayıt Sayfası"),
        ("reset password", "Şifre Sıfırla"),
        ("password error", "Şifre Hatası"),
        ("account error", "Hesap Hatası"),
        ("not found", "Bulunamadı"),
        ("access denied", "Erişim Reddedildi"),
        ("try again", "Tekrar Dene"),
    ]
    word_map = {
        "start": "Başla",
        "begin": "Başla",
        "end": "Bitir",
        "stop": "Durdur",
        "finish": "Bitir",
        "input": "Giriş",
        "output": "Çıkış",
        "process": "İşlem",
        "decision": "Karar",
        "yes": "Evet",
        "no": "Hayır",
        "true": "Doğru",
        "false": "Yanlış",
        "success": "Başarılı",
        "failed": "Başarısız",
        "fail": "Başarısız",
        "error": "Hata",
        "invalid": "Geçersiz",
        "valid": "Geçerli",
        "login": "Giriş Yap",
        "logout": "Çıkış Yap",
        "register": "Kayıt Ol",
        "signup": "Kayıt Ol",
        "verify": "Doğrula",
        "check": "Kontrol Et",
        "validate": "Doğrula",
        "submit": "Gönder",
        "approve": "Onayla",
        "reject": "Reddet",
        "cancel": "İptal",
        "retry": "Tekrar Dene",
        "continue": "Devam Et",
        "save": "Kaydet",
        "load": "Yükle",
        "update": "Güncelle",
        "create": "Oluştur",
        "delete": "Sil",
        "reset": "Sıfırla",
        "password": "Şifre",
        "account": "Hesap",
        "user": "Kullanıcı",
        "email": "E-posta",
        "send": "Gönder",
        "receive": "Al",
        "read": "Oku",
        "write": "Yaz",
        "open": "Aç",
        "close": "Kapat",
        "ok": "Tamam",
        "page": "Sayfası",
    }
    generic_terminal = {
        "başla",
        "basla",
        "başlangıç",
        "bitir",
        "bitti",
        "son",
        "start",
        "begin",
        "end",
        "stop",
        "finish",
        "entry",
        "exit",
    }
    generic_process = {"işlem", "adım", "iş", "süreç", "uygula", "kontrol", "process", "step", "action", "task"}
    generic_io = {
        "giriş/çıkış",
        "giriş",
        "çıktı",
        "girdi",
        "output",
        "input",
        "input/output",
        "read",
        "write",
    }
    generic_decision = {"karar", "koşul", "durum", "decision", "condition", "check"}
    process_idx = 1
    io_idx = 1
    action_pool = action_pool_for_topic(base)
    out_edges, in_edges = build_graph(flow_state)
    start_like = {
        n.id
        for n in flow_state.nodes
        if get_node_kind(n) == "terminal" and len(in_edges.get(n.id, [])) == 0
    }
    end_like = {
        n.id
        for n in flow_state.nodes
        if get_node_kind(n) == "terminal" and len(out_edges.get(n.id, [])) == 0
    }
    for n in flow_state.nodes:
        kind = get_node_kind(n)
        label = get_node_label(n)
        raw = label or ""
        # İngilizce ifadeleri Türkçeleştir (AI çıktıları için)
        for src, tgt in phrase_map:
            raw = re.sub(rf"(?i)\\b{re.escape(src)}\\b", tgt, raw)
        for src, tgt in word_map.items():
            raw = re.sub(rf"(?i)\\b{re.escape(src)}\\b", tgt, raw)
        cleaned = normalize_label_text(raw)
        if cleaned:
            raw = cleaned
        lowered = raw.lower().strip()
        if kind == "terminal" and (not raw.strip() or lowered in generic_terminal):
            if n.id in start_like and n.id not in end_like:
                label = "Başla"
            elif n.id in end_like:
                label = "Bitir"
            else:
                label = "Başla/Bitir"
        elif kind == "decision" and any(op in raw for op in ["%", "==", ">=", "<=", ">", "<"]):
            label = "Koşul sağlandı mı?"
        elif kind == "decision" and (not raw.strip() or lowered in generic_decision):
            label = "Koşul sağlandı mı?"
        elif kind == "io" and (not raw.strip() or lowered in generic_io):
            label = "Giriş Bilgisi Al" if io_idx == 1 else "Sonucu Göster"
            io_idx += 1
        elif kind == "process" and (not raw.strip() or lowered in generic_process):
            idx = (process_idx - 1) % max(1, len(action_pool))
            label = action_pool[idx]
            process_idx += 1
        elif len(raw.strip()) < 3:
            label = NODE_KIND.get(kind, NODE_KIND["process"])["default"]
        elif any(tok in lowered for tok in ["==", "%", ">=", "<=", ">", "<"]):
            label = raw.replace("%", " mod ").replace("==", " eşit mi ").replace(">=", " en az ").replace("<=", " en fazla ")
            label = label.replace(">", " büyük mü ").replace("<", " küçük mü ")
            label = re.sub(r"\s+", " ", label).strip()
        if label == (label or "").lower():
            label = turkish_title(label)
        if label != raw:
            data = getattr(n, "data", None) or {}
            data["label"] = label
            data["content"] = node_markdown(label, kind)
            n.data = data  # type: ignore[attr-defined]


def repair_ai_kinds(flow_state: StreamlitFlowState) -> None:
    """Etiketten düğüm tipini tahmin edip düzeltir."""
    for n in flow_state.nodes:
        kind = get_node_kind(n)
        label = normalize_label_text(get_node_label(n))
        if kind not in NODE_KIND or kind == "process":
            guessed = guess_kind_from_label(label)
            if guessed != kind and guessed in NODE_KIND:
                data = getattr(n, "data", None) or {}
                data["kind"] = guessed
                data["content"] = node_markdown(label or NODE_KIND[guessed]["default"], guessed)
                n.data = data  # type: ignore[attr-defined]


def ensure_decision_edge_labels(flow_state: StreamlitFlowState) -> None:
    """Karar düğümlerinde ilk 2 dal için Evet/Hayır etiketlerini tamamlar. 3. ve sonrası boş kalır."""
    def normalize_decision_label(value: str) -> str:
        raw = normalize_label_text(value)
        lower = raw.lower()
        if lower in {"evet", "yes", "y", "true", "t"}:
            return "Evet"
        if lower in {"hayır", "hayir", "no", "n", "false", "f"}:
            return "Hayır"
        return raw

    out_edges, _ = build_graph(flow_state)
    for n in flow_state.nodes:
        if get_node_kind(n) != "decision":
            continue
        edges = out_edges.get(n.id, [])
        if len(edges) < 2:
            continue

        # Var olan etiketleri Türkçe normalize et
        for e in edges[:2]:
            current = get_edge_label(e)
            updated = normalize_decision_label(current)
            if updated and updated != current:
                e.label = updated  # type: ignore[attr-defined]

        # İlk 2 dal için Evet/Hayır kontrolü
        labels = [get_edge_label(e).strip().lower() for e in edges[:2]]
        
        if not any(lbl for lbl in labels):
            # Her iki etiket de boşsa
            edges[0].label = "Evet"  # type: ignore[attr-defined]
            edges[1].label = "Hayır"  # type: ignore[attr-defined]
        else:
            # Sadece eksik olanı ekle
            if not any("evet" in lbl for lbl in labels):
                edges[0].label = "Evet"  # type: ignore[attr-defined]
            if len(edges) >= 2 and not any("hayır" in lbl or "hayir" in lbl for lbl in labels):
                edges[1].label = "Hayır"  # type: ignore[attr-defined]
        
        # 3. ve sonraki dallar için etiket ekleme (boş bırak)
        # Kullanıcı isterse manuel ekleyebilir


def is_generic_process_label(label: str) -> bool:
    text = normalize_label_text(label).lower()
    if not text:
        return True
    if text in {"işlem", "adım", "kontrol", "süreç", "uygula"}:
        return True
    if re.match(r".*adım\s*\d+$", text):
        return True
    if re.match(r".*step\s*\d+$", text):
        return True
    if len(text.split()) <= 2 and any(tok in text for tok in ["işlem", "kontrol", "uygula", "adım", "süreç"]):
        return True
    return False


def simplify_flow_state(flow_state: StreamlitFlowState) -> None:
    """Genel/tekrarlı süreç düğümlerini azaltır, akışı sadeleştirir."""
    changed = True
    while changed:
        changed = False
        out_edges, in_edges = build_graph(flow_state)
        id_map = {n.id: n for n in flow_state.nodes}
        for n in list(flow_state.nodes):
            if get_node_kind(n) != "process":
                continue
            if is_start_node(n) or is_end_node(n):
                continue
            if not is_generic_process_label(get_node_label(n)):
                continue
            ins = in_edges.get(n.id, [])
            outs = out_edges.get(n.id, [])
            if len(ins) != 1 or len(outs) != 1:
                continue
            src = ins[0].source
            tgt = outs[0].target
            if src == tgt:
                continue
            # Yeni kenar ekle (etiket yok)
            new_id = build_edge_id(src, tgt, "", "solid", salt=f"s{n.id}")
            flow_state.edges.append(make_edge(new_id, src, tgt, label="", edge_type="smoothstep"))
            # Eski kenarları ve düğümü kaldır
            flow_state.edges = [e for e in flow_state.edges if e.id not in {ins[0].id, outs[0].id}]
            flow_state.nodes = [node for node in flow_state.nodes if node.id != n.id]
            changed = True
            break


def build_required_flow_template(topic: str, include_io: bool = True) -> str:
    """Zorunlu düğüm tiplerini içeren güvenli akış şeması üretir."""
    topic = turkish_title((topic or "Akış").strip() or "Akış")
    if include_io:
        return f"""flowchart TD
    s([Başla: {topic}])
    io1[/Giriş Bilgisi Al/]
    p1[Hazırlık Yap]
    d1{{Koşul Sağlandı mı?}}
    p2[Adımı Uygula]
    io2[/Sonucu Göster/]
    e([Bitir: Tamamlandı])
    
    s --> io1
    io1 --> p1
    p1 --> d1
    d1 -->|Evet| p2
    d1 -->|Hayır| p1
    p2 --> io2
    io2 --> e
""".strip()
    return f"""flowchart TD
    s([Başla: {topic}])
    p1[Hazırlık Yap]
    d1{{Koşul Sağlandı mı?}}
    p2[Adımı Uygula]
    e([Bitir: Tamamlandı])
    
    s --> p1
    p1 --> d1
    d1 -->|Evet| p2
    d1 -->|Hayır| p1
    p2 --> e
""".strip()


def detect_cycle(nodes: Iterable[StreamlitFlowNode], out_edges: Dict[str, List[StreamlitFlowEdge]]) -> bool:
    """Graph içinde döngü olup olmadığını döndürür."""
    color: Dict[str, int] = {n.id: 0 for n in nodes}  # 0=unseen,1=visiting,2=done

    def dfs(nid: str) -> bool:
        color[nid] = 1
        for e in out_edges.get(nid, []):
            tgt = e.target
            if color.get(tgt, 0) == 1:
                return True
            if color.get(tgt, 0) == 0 and dfs(tgt):
                return True
        color[nid] = 2
        return False

    for node_id in list(color.keys()):
        if color[node_id] == 0 and dfs(node_id):
            return True
    return False


def validate_flow(flow_state: StreamlitFlowState) -> List[ValidationItem]:
    """Akış şemasını doğrular ve Türkçe rapor döndürür."""
    items: List[ValidationItem] = []
    nodes = flow_state.nodes
    edges = flow_state.edges
    if not nodes:
        return [ValidationItem("error", "Hiç düğüm yok.")]

    id_map = {n.id: n for n in nodes}
    out_edges, in_edges = build_graph(flow_state)

    start_nodes = [n for n in nodes if is_start_node(n)]
    end_nodes = [n for n in nodes if is_end_node(n)]

    if not start_nodes:
        items.append(ValidationItem("error", "Başla düğümü bulunamadı. (Etiket: 'Başla' veya terminal)"))
    if not end_nodes:
        items.append(ValidationItem("error", "Bitir düğümü bulunamadı. (Etiket: 'Bitir' veya terminal)"))

    # Reachable analysis
    reachable: set[str] = set()
    if start_nodes:
        q = deque([n.id for n in start_nodes])
        while q:
            nid = q.popleft()
            if nid in reachable:
                continue
            reachable.add(nid)
            for e in out_edges.get(nid, []):
                q.append(e.target)

    unreachable = [n for n in nodes if n.id not in reachable]
    if unreachable:
        items.append(
            ValidationItem(
                "warning",
                "Erişilemeyen düğümler var: " + ", ".join(n.id for n in unreachable),
            )
        )

    # Dead-end nodes
    dead_ends = [
        n
        for n in nodes
        if len(out_edges.get(n.id, [])) == 0 and not is_end_node(n)
    ]
    if dead_ends:
        items.append(
            ValidationItem(
                "warning",
                "Çıkışı olmayan düğümler var: " + ", ".join(n.id for n in dead_ends),
            )
        )

    # Decision node checks
    decision_nodes = [n for n in nodes if get_node_kind(n) == "decision"]
    for n in decision_nodes:
        out_count = len(out_edges.get(n.id, []))
        if out_count < 2:
            items.append(ValidationItem("warning", f"Karar düğümü '{n.id}' için en az 2 çıkış beklenir."))

        labels = [get_edge_label(e).lower() for e in out_edges.get(n.id, [])]
        has_yes = any("evet" in lbl for lbl in labels)
        has_no = any("hayır" in lbl or "hayir" in lbl for lbl in labels)
        if out_count >= 2 and (not has_yes or not has_no):
            items.append(
                ValidationItem(
                    "info",
                    f"Karar düğümü '{n.id}' çıkışlarında 'Evet/Hayır' etiketleri önerilir.",
                )
            )

    # IO node check
    io_nodes = [n for n in nodes if get_node_kind(n) == "io"]
    if not io_nodes:
        items.append(ValidationItem("info", "Giriş/Çıkış düğümü bulunamadı."))

    # Cycle info
    if detect_cycle(nodes, out_edges):
        items.append(ValidationItem("info", "Akışta döngü olasılığı tespit edildi."))

    # Graph connectivity sanity
    if edges and start_nodes and len(reachable) < len(nodes):
        items.append(ValidationItem("warning", "Tüm düğümler başlangıçtan erişilebilir değil."))

    return items


def evaluate_task(flow_state: StreamlitFlowState, task_name: str) -> List[ValidationItem]:
    """Görev moduna göre ek kontrol kuralları uygular."""
    if not task_name or task_name not in TASK_LIBRARY:
        return []

    task = TASK_LIBRARY[task_name]
    items: List[ValidationItem] = []
    kinds = [get_node_kind(n) for n in flow_state.nodes]
    label_text = " ".join(get_node_label(n).lower() for n in flow_state.nodes)
    edge_text = " ".join(get_edge_label(e).lower() for e in flow_state.edges)

    for kind, min_count in task.get("min_nodes", {}).items():
        actual = sum(1 for k in kinds if k == kind)
        if actual < min_count:
            items.append(
                ValidationItem(
                    "warning",
                    f"Görev için '{NODE_KIND.get(kind, {'label': kind})['label']}' türünden en az {min_count} düğüm önerilir.",
                )
            )

    expected = task.get("expected_labels", [])
    for kw in expected:
        if kw.lower() not in label_text and kw.lower() not in edge_text:
            items.append(ValidationItem("info", f"Etiketlerde '{kw}' ifadesi bekleniyor olabilir."))

    return items


def score_rubric(flow_state: StreamlitFlowState) -> Tuple[int, List[str]]:
    """Rubrik puanı ve geri bildirim üretir."""
    feedback: List[str] = []
    nodes = flow_state.nodes
    edges = flow_state.edges
    kinds = {get_node_kind(n) for n in nodes}

    has_start = any(is_start_node(n) for n in nodes)
    has_end = any(is_end_node(n) for n in nodes)
    has_io = any(get_node_kind(n) == "io" for n in nodes)
    has_decision = any(get_node_kind(n) == "decision" for n in nodes)
    has_cycle = detect_cycle(nodes, build_graph(flow_state)[0])

    algo_score = min(40, len(kinds) * 6 + (10 if has_start and has_end else 0))
    flow_score = 0
    flow_score += 10 if has_decision else 0
    flow_score += 10 if has_cycle else 5
    flow_score += 10 if edges else 0
    flow_score = min(30, flow_score)

    label_lengths = [len(get_node_label(n)) for n in nodes if get_node_label(n)]
    avg_len = sum(label_lengths) / len(label_lengths) if label_lengths else 0
    edge_label_ratio = (
        sum(1 for e in edges if get_edge_label(e).strip()) / len(edges) if edges else 0
    )
    readability_score = 20
    if avg_len < 3 or avg_len > 40:
        readability_score -= 6
        feedback.append("Etiket uzunlukları çok kısa/uzun görünüyor.")
    if edge_label_ratio < 0.3 and edges:
        readability_score -= 6
        feedback.append("Bağlantı etiketleri artırılabilir.")
    if not nodes:
        readability_score = 0

    completion_score = 10 if (has_start and has_end) else 5 if (has_start or has_end) else 0
    if not has_start:
        feedback.append("Başla düğümü ekleyin.")
    if not has_end:
        feedback.append("Bitir düğümü ekleyin.")
    if not has_io:
        feedback.append("Giriş/Çıkış düğümü eklemek faydalı olabilir.")
    if not has_decision:
        feedback.append("Karar düğümü ile akış zenginleştirilebilir.")

    total = int(algo_score + flow_score + readability_score + completion_score)
    total = max(0, min(100, total))
    return total, feedback


def generate_pseudocode(flow_state: StreamlitFlowState) -> str:
    """Akış şemasından basit pseudo-code üretir."""
    nodes = flow_state.nodes
    if not nodes:
        return ""

    id_map = {n.id: n for n in nodes}
    out_edges, _ = build_graph(flow_state)
    start_nodes = [n for n in nodes if is_start_node(n)]
    if not start_nodes:
        start_nodes = [nodes[0]]

    lines: List[str] = []
    visited: set[str] = set()

    def emit(line: str, level: int = 0) -> None:
        lines.append(("  " * level) + line)

    def walk(nid: str, level: int, stack: set[str]) -> None:
        if nid in stack:
            emit("... (döngü)", level)
            return
        node = id_map.get(nid)
        if node is None:
            return
        kind = get_node_kind(node)
        label = get_node_label(node)

        if kind == "terminal":
            if is_start_node(node):
                emit("BAŞLA", level)
            elif is_end_node(node):
                emit("BİTİR", level)
            else:
                emit(f"TERMINAL: {label}", level)
        elif kind == "io":
            emit(f"GİRİŞ/ÇIKIŞ: {label}", level)
        elif kind == "process":
            emit(f"İŞLEM: {label}", level)
        elif kind == "decision":
            emit(f"EĞER {label} İSE:", level)
        elif kind == "loop":
            emit(f"DÖNGÜ: {label}", level)
        elif kind == "function":
            emit(f"FONKSİYON: {label}", level)
        elif kind == "comment":
            emit(f"NOT: {label}", level)
        else:
            emit(f"{kind.upper()}: {label}", level)

        if nid in visited:
            return
        visited.add(nid)

        next_edges = out_edges.get(nid, [])
        if kind == "decision" and next_edges:
            for e in next_edges:
                branch = get_edge_label(e) or "dal"
                emit(f"- {branch} ->", level + 1)
                walk(e.target, level + 2, stack | {nid})
        else:
            for e in next_edges:
                walk(e.target, level, stack | {nid})

    for s in start_nodes:
        walk(s.id, 0, set())

    return "\n".join(lines)


# =============================================================================
# Dışa aktarma (PNG/SVG)
# =============================================================================


def mermaid_ink_b64(code: str) -> str:
    # mermaid.ink URL-safe base64 bekler
    return base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii").rstrip("=")


def export_png_via_kroki(code: str, scale: int = 1) -> bytes:
    """Mermaid kodunu PNG'ye dönüştürür (kroki.io üzerinden)."""
    if requests is None:
        raise RuntimeError(
            "❌ PNG oluşturmak için 'requests' kütüphanesi gerekli.\n\n"
            "Kurulum: pip install requests"
        )
    try:
        scale = max(1, min(4, int(scale)))
        url = f"https://kroki.io/mermaid/png?scale={scale}"
        r = requests.post(
            url,
            data=code.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"🌐 Kroki bağlantı hatası: {e}")


def export_svg_via_kroki(code: str) -> bytes:
    """Mermaid kodunu SVG'ye dönüştürür (kroki.io üzerinden)."""
    if requests is None:
        raise RuntimeError(
            "❌ SVG oluşturmak için 'requests' kütüphanesi gerekli.\n\n"
            "Kurulum: pip install requests"
        )
    try:
        url = "https://kroki.io/mermaid/svg"
        r = requests.post(
            url,
            data=code.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"🌐 Kroki bağlantı hatası: {e}")


def export_png_via_mermaid_ink(code: str, scale: int = 1) -> bytes:
    """Mermaid kodunu PNG'ye dönüştürür (mermaid.ink üzerinden).
    
    Args:
        code: Mermaid flowchart kodu
        scale: Görsel ölçeklendirme (1-4)
    
    Returns:
        PNG dosyası (bytes)
    
    Raises:
        RuntimeError: requests kütüphanesi yoksa veya bağlantı hatasında
    """
    if requests is None:
        raise RuntimeError(
            "❌ PNG oluşturmak için 'requests' kütüphanesi gerekli.\n\n"
            "Kurulum: pip install requests"
        )
    try:
        b64 = mermaid_ink_b64(code)
        scale = max(1, min(4, int(scale)))
        url = f"https://mermaid.ink/img/{b64}?background=white&theme=neutral&scale={scale}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.content
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:
            try:
                fallback = build_minimal_export_code()
                b64 = mermaid_ink_b64(fallback)
                url = f"https://mermaid.ink/img/{b64}?background=white&theme=neutral&scale={scale}"
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                return r.content
            except Exception:
                for attempt in (code, fallback):
                    try:
                        return export_png_via_kroki(attempt, scale=scale)
                    except Exception:
                        continue
                raise RuntimeError(
                    "Mermaid kodu işlenemedi. Otomatik sadeleştirme ve alternatif render denendi "
                    "ama başarısız oldu."
                )
        raise RuntimeError(f"🌐 Bağlantı hatası: {e}")
    except requests.exceptions.Timeout:
        raise RuntimeError("⌛ Mermaid.ink sunucusu yanıt vermiyor. Lütfen tekrar deneyin.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"🌐 Bağlantı hatası: {e}")


def export_svg_via_mermaid_ink(code: str) -> bytes:
    """Mermaid kodunu SVG'ye dönüştürür (mermaid.ink üzerinden).
    
    Args:
        code: Mermaid flowchart kodu
    
    Returns:
        SVG dosyası (bytes)
    """
    if requests is None:
        raise RuntimeError(
            "❌ SVG oluşturmak için 'requests' kütüphanesi gerekli.\n\n"
            "Kurulum: pip install requests"
        )
    try:
        b64 = mermaid_ink_b64(code)
        url = f"https://mermaid.ink/svg/{b64}?background=white&theme=neutral"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.content
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:
            try:
                fallback = build_minimal_export_code()
                b64 = mermaid_ink_b64(fallback)
                url = f"https://mermaid.ink/svg/{b64}?background=white&theme=neutral"
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                return r.content
            except Exception:
                for attempt in (code, fallback):
                    try:
                        return export_svg_via_kroki(attempt)
                    except Exception:
                        continue
                raise RuntimeError(
                    "Mermaid kodu işlenemedi. Otomatik sadeleştirme ve alternatif render denendi "
                    "ama başarısız oldu."
                )
        raise RuntimeError(f"🌐 Bağlantı hatası: {e}")
    except requests.exceptions.Timeout:
        raise RuntimeError("⌛ Mermaid.ink sunucusu yanıt vermiyor. Lütfen tekrar deneyin.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"🌐 Bağlantı hatası: {e}")


def export_json_payload(flow_state: StreamlitFlowState) -> Dict[str, object]:
    """Proje verisini JSON için hazırlar."""
    code_text = generate_mermaid(flow_state, st.session_state.direction)
    return {
        "title": st.session_state.project_title,
        "direction": st.session_state.direction,
        "code_text": code_text,
        "nodes": serialize_nodes(flow_state.nodes),
        "edges": serialize_edges(flow_state.edges),
        "timestamp": int(time.time()),
    }


def import_json_payload(data: Dict[str, object]) -> Tuple[Optional[StreamlitFlowState], str]:
    """JSON içinden state üretir."""
    try:
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None, "JSON formatı geçersiz: nodes/edges list olmalı."
        state = build_state_from_snapshot(nodes, edges)
        normalize_state(state)
        return state, ""
    except Exception as exc:
        return None, f"JSON yüklenemedi: {exc}"


PDF_FONT_CACHE: Optional[Tuple[str, str, str]] = None


def resolve_pdf_fonts() -> Tuple[str, str, str]:
    """Türkçe karakter destekli fontları bulup kaydeder."""
    global PDF_FONT_CACHE
    if PDF_FONT_CACHE:
        return PDF_FONT_CACHE

    if pdfmetrics is None or TTFont is None:
        PDF_FONT_CACHE = ("Helvetica", "Helvetica-Bold", "Courier")
        return PDF_FONT_CACHE

    def register_font(name: str, candidates: List[Path]) -> Optional[str]:
        for path in candidates:
            try:
                if path.exists():
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                    return name
            except Exception:
                continue
        return None

    win = Path("C:/Windows/Fonts")
    linux = Path("/usr/share/fonts")
    mac = Path("/System/Library/Fonts")

    regular_candidates = [
        win / "DejaVuSans.ttf",
        win / "arial.ttf",
        win / "segoeui.ttf",
        linux / "truetype/dejavu/DejaVuSans.ttf",
        linux / "truetype/noto/NotoSans-Regular.ttf",
        mac / "Supplemental/Arial Unicode.ttf",
        mac / "Supplemental/Arial.ttf",
    ]
    bold_candidates = [
        win / "DejaVuSans-Bold.ttf",
        win / "arialbd.ttf",
        win / "segoeuib.ttf",
        linux / "truetype/dejavu/DejaVuSans-Bold.ttf",
        linux / "truetype/noto/NotoSans-Bold.ttf",
        mac / "Supplemental/Arial Bold.ttf",
    ]
    mono_candidates = [
        win / "DejaVuSansMono.ttf",
        win / "consola.ttf",
        linux / "truetype/dejavu/DejaVuSansMono.ttf",
        linux / "truetype/noto/NotoSansMono-Regular.ttf",
        mac / "Supplemental/Andale Mono.ttf",
    ]

    regular = register_font("AppFont", regular_candidates)
    bold = register_font("AppFont-Bold", bold_candidates)
    mono = register_font("AppFont-Mono", mono_candidates)

    if regular:
        PDF_FONT_CACHE = (
            regular,
            bold or regular,
            mono or regular,
        )
    else:
        PDF_FONT_CACHE = ("Helvetica", "Helvetica-Bold", "Courier")
    return PDF_FONT_CACHE


def export_pdf_report(code: str, title: str, checklist: List[str], scale: int = 1) -> bytes:
    """Akış şeması çalışma kağıdı PDF'i üretir."""
    if canvas is None:
        raise RuntimeError("PDF için 'reportlab' kütüphanesi gerekli.")
    if requests is None:
        raise RuntimeError("PDF için 'requests' kütüphanesi gerekli.")

    png_bytes = export_png_via_mermaid_ink(code, scale=scale)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    font_regular, font_bold, font_mono = resolve_pdf_fonts()

    c.setFont(font_bold, 16)
    c.drawString(40, height - 40, title or "Akış Şeması")
    c.setFont(font_regular, 10)
    c.drawString(40, height - 58, datetime.now().strftime("%Y-%m-%d %H:%M"))

    # Mermaid kodu
    c.setFont(font_bold, 11)
    c.drawString(40, height - 85, "Mermaid Kodu")
    c.setFont(font_mono, 8)
    text_obj = c.beginText(40, height - 100)
    for line in (code or "").splitlines()[:28]:
        text_obj.textLine(line[:120])
    c.drawText(text_obj)

    # Görsel
    c.setFont(font_bold, 11)
    c.drawString(40, height - 320, "Akış Şeması")
    img = ImageReader(io.BytesIO(png_bytes))
    img_w = 520
    img_h = 280
    c.drawImage(img, 40, height - 620, width=img_w, height=img_h, preserveAspectRatio=True, mask="auto")

    # Kontrol listesi
    c.setFont(font_bold, 11)
    c.drawString(40, height - 650, "Kontrol Listesi")
    c.setFont(font_regular, 10)
    y = height - 670
    for item in checklist:
        c.rect(40, y - 8, 10, 10)
        c.drawString(58, y - 6, item)
        y -= 16

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# =============================================================================
# UI: CSS + JS
# =============================================================================


def inject_css() -> None:
    st.markdown(
        """
<style>
/* Genel yerleşim */
.block-container { 
  padding-top: 0.3rem; 
  padding-bottom: 0.4rem;
  padding-left: 1rem;
  padding-right: 1rem;
  max-width: 100%;
}
section[data-testid="stSidebar"] { 
  min-width: 360px;
  max-width: 400px;
}
section[data-testid="stSidebar"] .block-container { 
  padding-top: 0.45rem; 
  padding-bottom: 0.4rem;
}
section[data-testid="stSidebar"] hr { margin: 0.35rem 0; }
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
  margin-top: 0.25rem;
  margin-bottom: 0.25rem;
}
section[data-testid="stSidebar"] .stMarkdown { margin-bottom: 0.25rem; }
section[data-testid="stSidebar"] .stExpander { margin-top: 0.2rem; margin-bottom: 0.2rem; }
section[data-testid="stSidebar"] .stButton { margin-top: 0.1rem; margin-bottom: 0.1rem; }
div[data-testid="stAppViewContainer"] > .main .block-container { 
  padding-top: 0rem;
  padding-bottom: 0.5rem;
}
header[data-testid="stHeader"] { height: 0; }

/* İnce ayırıcı */
.section-sep {
  border-bottom: 1px solid #e2e8f0;
  margin: 0.35rem 0;
}

/* JS seçim köprüsü gizle */
input[aria-label="js_selected_node_id"] {
  display: none !important;
}
div[data-testid="stTextInput"]:has(input[aria-label="js_selected_node_id"]) {
  display: none !important;
}

/* Toolbar container - kompakt (üst satır) */
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Geri"]) {
  margin-top: 0.1rem;
  margin-bottom: 0.05rem;
  padding-top: 0.1rem;
  padding-bottom: 0.05rem;
  border-top: none !important;
  border-bottom: none !important;
  gap: 0.05rem !important;
}

/* Dialog butonları küçük ve responsive */
div[data-testid="column"] button {
  font-size: 0.85rem !important;
  padding: 0.35rem 0.65rem !important;
  min-height: 2.2rem !important;
}

/* Expander başlık kompakt */
div[data-testid="stExpander"] summary {
  padding: 0.5rem !important;
  font-size: 0.9rem !important;
}

/* Tuval arka planı */
.react-flow__pane {
  background: radial-gradient(circle at 20px 20px, rgba(148,163,184,0.35) 1px, transparent 1px);
  background-size: 24px 24px;
}

/* Kenar çizgileri */
.react-flow__edge-path { stroke: #0f172a !important; stroke-width: 2.6 !important; }
.react-flow__edge.selected .react-flow__edge-path { stroke: #2563EB !important; stroke-width: 2.6 !important; }
.react-flow__edge.selected .react-flow__edge-path { stroke-dasharray: 6 4; }
.react-flow__edge .react-flow__edge-textbg { fill: rgba(255,255,255,0.9) !important; }
.react-flow__edge .react-flow__edge-text { fill: #0f172a !important; font-weight: 900; }
.react-flow__edge.selected .react-flow__edge-text { fill: #1e40af !important; }

/* Düğüm fontu & seçili görünüm */
.react-flow__node { font-family: "Segoe UI", Arial, sans-serif; }
.react-flow__node.selected {
  border-style: dashed !important;
  border-width: 2px !important;
  outline: 2px dashed rgba(37, 99, 235, 0.35);
  outline-offset: 2px;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18);
}
.react-flow__node.manual-selected {
  border-style: dashed !important;
  border-width: 2px !important;
  outline: 2px dashed rgba(37, 99, 235, 0.35);
  outline-offset: 2px;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18);
}

/* Düğüm paleti satırları: boşluğu minimuma indir */
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Başla"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Giriş/Çıkış"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="İşlem"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Karar"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Belge"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Çoklu Belgeler"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Veri Deposu"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Dahili Depo"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Bant Veri"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Alt Süreç"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Veritabanı"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Görüntü"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Manuel İşlem"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Birleştir"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Manuel Giriş"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Bağlantı"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Not"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Döngü"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Fonksiyon"]),
div[data-testid="stHorizontalBlock"]:has(button[aria-label*="Bitir"]) {
  gap: 0.05rem !important;
  margin-top: 0.05rem !important;
  margin-bottom: 0.05rem !important;
}
.react-flow__node.selected .react-flow__handle {
  background: #2563EB;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.25);
}
.react-flow__selection {
  border: 2px dashed rgba(37, 99, 235, 0.9) !important;
  background: rgba(37, 99, 235, 0.08) !important;
}

/* Bağlantı noktalarını büyüt (yakalaması kolay olsun) */
.react-flow__handle {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  background: #111827;
  border: 3px solid #ffffff;
  box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.15);
}
.react-flow__handle::before {
  content: "";
  position: absolute;
  top: -20px;
  left: -20px;
  width: 66px;
  height: 66px;
  border-radius: 999px;
  background: transparent;
  /* Pseudo-elementin de tıklama alanına dahil olmasını zorla */
  pointer-events: all;
}

/* Toolbar butonları (etikete göre) */
.stButton > button {
  font-weight: 900 !important;
  font-size: 0.95rem !important;
  padding: 0.5rem 0.85rem !important;
  border-radius: 0.75rem !important;
}

/* Palet renkleri */
.stButton > button[aria-label*="Başla"] { background: #ECFDF5 !important; border-color: #10B981 !important; color: #065F46 !important; }
.stButton > button[aria-label*="Bitir"] { background: #FEE2E2 !important; border-color: #EF4444 !important; color: #991B1B !important; }
.stButton > button[aria-label*="Giriş/Çıkış"] { background: #EFF6FF !important; border-color: #2563EB !important; color: #1E3A8A !important; }
.stButton > button[aria-label*="İşlem"] { background: #F1F5F9 !important; border-color: #334155 !important; color: #0F172A !important; }
.stButton > button[aria-label*="Karar"] { background: #FFF7D6 !important; border-color: #F59E0B !important; color: #92400E !important; }
.stButton > button[aria-label*="Belge"] { background: #FFF7ED !important; border-color: #F97316 !important; color: #9A3412 !important; }
.stButton > button[aria-label*="Çoklu Belgeler"] { background: #FFF7ED !important; border-color: #F97316 !important; color: #9A3412 !important; }
.stButton > button[aria-label*="Veri Deposu"] { background: #DCFCE7 !important; border-color: #16A34A !important; color: #166534 !important; }
.stButton > button[aria-label*="Dahili Depo"] { background: #DCFCE7 !important; border-color: #15803D !important; color: #166534 !important; }
.stButton > button[aria-label*="Bant Veri"] { background: #DCFCE7 !important; border-color: #16A34A !important; color: #166534 !important; }
.stButton > button[aria-label*="Alt Süreç"] { background: #F3E8FF !important; border-color: #7C3AED !important; color: #5B21B6 !important; }
.stButton > button[aria-label*="Veritabanı"] { background: #EEF2FF !important; border-color: #1E40AF !important; color: #1E3A8A !important; }
.stButton > button[aria-label*="Görüntü"] { background: #FEF3C7 !important; border-color: #D97706 !important; color: #92400E !important; }
.stButton > button[aria-label*="Manuel İşlem"] { background: #FEF3C7 !important; border-color: #D97706 !important; color: #92400E !important; }
.stButton > button[aria-label*="Birleştir"] { background: #FEF3C7 !important; border-color: #D97706 !important; color: #92400E !important; }
.stButton > button[aria-label*="Manuel Giriş"] { background: #FEF3C7 !important; border-color: #D97706 !important; color: #92400E !important; }
.stButton > button[aria-label*="Bağlantı"] { background: #FFF3C4 !important; border-color: #F59E0B !important; color: #92400E !important; }
.stButton > button[aria-label*="Not"] { background: #FFF7ED !important; border-color: #EA580C !important; color: #7C2D12 !important; }
.stButton > button[aria-label*="Döngü"] { background: #ECFEFF !important; border-color: #06B6D4 !important; color: #0E7490 !important; }
.stButton > button[aria-label*="Fonksiyon"] { background: #EDE9FE !important; border-color: #6D28D9 !important; color: #4C1D95 !important; }
.stButton > button[aria-label*="Seçiliyi Sil"] { background: #FEE2E2 !important; border-color: #EF4444 !important; color: #991B1B !important; }

/* Geri/İleri renk */
.stButton > button[aria-label*="Geri"],
.stButton > button[aria-label*="İleri"] {
  background: #E0F2FE !important;
  border-color: #38BDF8 !important;
  color: #0C4A6E !important;
}

/* Sıfırla rengi */
.stButton > button[aria-label*="Sıfırla"] {
  background: #FEF3C7 !important;
  border-color: #F59E0B !important;
  color: #92400E !important;
}
/* Buton hover efektleri */
.stButton > button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  transition: all 0.2s ease;
}

/* Düğüm hover efekti */
.react-flow__node:hover {
  filter: brightness(1.05);
  cursor: pointer;
  transition: all 0.2s ease;
}

/* Bağlantı hover efekti */
.react-flow__edge:hover .react-flow__edge-path {
  stroke-width: 3.5 !important;
  transition: stroke-width 0.2s ease;
}

/* Açıklama kutusu dashed border */
.stExpander {
  border: 2px dashed #CBD5E1 !important;
  border-radius: 8px !important;
}

.stAlert {
  border-left: 4px dashed #3B82F6 !important;
}

/* Typography iyileştirmeleri */
h1 { 
  font-size: 2rem; 
  font-weight: 700; 
  letter-spacing: -0.02em; 
  line-height: 1.2;
}
h2 { 
  font-size: 1.5rem; 
  font-weight: 600; 
  line-height: 1.3;
}
h3 { 
  font-size: 1.2rem; 
  font-weight: 600; 
  line-height: 1.4;
}
.stMarkdown p { 
  line-height: 1.6; 
}
code { 
  background: #F1F5F9; 
  padding: 2px 6px; 
  border-radius: 4px; 
  font-family: 'Consolas', 'Monaco', monospace;
}

/* Yardım metni */
.help-small {
  font-size: 0.82rem;
  line-height: 1.45;
  color: #1f2937;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}
.help-small strong {
  font-size: 0.85rem;
}

/* Öneri butonu */
.suggest-btn {
  display: block;
  text-align: center;
  padding: 0.5rem 0.75rem;
  border-radius: 0.75rem;
  background: #FEF3C7;
  border: 1px solid #F59E0B;
  color: #92400E;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}
.suggest-btn:hover {
  background: #FDE68A;
  color: #7C2D12;
}

/* Disabled buton stili */
.stButton > button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

</style>
""",
        unsafe_allow_html=True,
    )


def inject_tr_translation_script() -> None:
    """streamlit-flow context menülerini (ve bazı metinleri) Türkçeleştirmeye çalışır."""

    st.markdown(
        """
<script>
(function() {
  const map = {
    "Edit Node": "Düğümü Düzenle",
    "Edit Edge": "Bağlantıyı Düzenle",
    "Node Content": "Düğüm Metni",
    "Node Width": "Düğüm Genişliği",
    "Node Label": "Düğüm Etiketi",
    "Node Type": "Düğüm Tipi",
    "Shape": "Şekil",
    "Shapes": "Şekiller",
    "Edge Label": "Bağlantı Etiketi",
    "Edge Type": "Bağlantı Tipi",
    "Connection": "Bağlantı",
    "Connections": "Bağlantılar",
    "Handle": "Bağlantı Noktası",
    "Handles": "Bağlantı Noktaları",
    "Source Position": "Kaynak Konum",
    "Target Position": "Hedef Konum",
    "Top": "Üst",
    "Bottom": "Alt",
    "Left": "Sol",
    "Right": "Sağ",
    "Draggable": "Sürüklenebilir",
    "Connectable": "Bağlanabilir",
    "Deletable": "Silinebilir",
    "Animated": "Animasyon",
    "Label BG": "Etiket Arka Plan",
    "Delete Node": "Düğümü Sil",
    "Delete Edge": "Bağlantıyı Sil",
    "Default": "Varsayılan",
    "Straight": "Düz",
    "Step": "Basamak",
    "Smoothstep": "Yumuşak",
    "Simplebezier": "Basit Eğri",
    "Edit": "Düzenle",
    "Delete": "Sil",
    "Node": "Düğüm",
    "Edge": "Bağlantı",
    "Close": "Kapat",
    "Save Changes": "Kaydet",
    "Add Node": "Düğüm Ekle",
    "Add Edge": "Bağlantı Ekle",
    "Pane": "Tuval",
    "Controls": "Kontroller",
    "MiniMap": "Mini Harita",
    "Duplicate": "Kopyala",
    "Copy": "Kopyala",
    "Paste": "Yapıştır",
    "Cut": "Kes",
    "Fit View": "Sığdır",
    "Zoom In": "Yakınlaştır",
    "Zoom Out": "Uzaklaştır",
    "Reset View": "Görünümü Sıfırla",
    "Reset Layout": "Düzeni Sıfırla",
    "Selection": "Seçim",
    "Nodes": "Düğümler",
    "Edges": "Bağlantılar",
    "Delete Selected": "Seçileni Sil",
    "Export": "Dışa Aktar",
    "Format": "Biçim",
    "Apply": "Uygula",
    "Clear": "Temizle"
  };
  const mapLower = {};
  Object.keys(map).forEach((k) => {
    mapLower[k.toLowerCase()] = map[k];
  });

  const normalizeKey = (t) => {
    if (!t) return "";
    return t.replace(/^[^A-Za-z]+/, "").replace(/[^A-Za-z]+$/, "").trim().toLowerCase();
  };

  const findMapping = (text) => {
    if (!text) return "";
    if (map[text]) return map[text];
    const lower = text.toLowerCase();
    if (mapLower[lower]) return mapLower[lower];
    const nk = normalizeKey(text);
    if (mapLower[nk]) return mapLower[nk];
    // içeriyor mu?
    for (const k of Object.keys(mapLower)) {
      if (lower.includes(k)) return mapLower[k];
    }
    return "";
  };

  const replaceText = (node) => {
    if (!node) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const t = (node.textContent || "").trim();
      const mapped = findMapping(t);
      if (mapped) node.textContent = mapped;
    } else if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
      if (node.childNodes && node.childNodes.length) {
        node.childNodes.forEach(replaceText);
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      ["aria-label", "title", "placeholder"].forEach((attr) => {
        const v = node.getAttribute && node.getAttribute(attr);
        if (v) {
          const mapped = findMapping(v);
          if (mapped) node.setAttribute(attr, mapped);
        }
      });
      if (node.shadowRoot) {
        replaceText(node.shadowRoot);
      }
      if (node.childNodes && node.childNodes.length) {
        node.childNodes.forEach(replaceText);
      }
    }
  };

  const observeRoot = (root) => {
    if (!root || root.__trObserver) return;
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.addedNodes) {
          m.addedNodes.forEach(replaceText);
        }
      }
    });
    observer.observe(root, { childList: true, subtree: true });
    root.__trObserver = observer;
  };

  const translateDocument = (doc) => {
    if (!doc || !doc.body) return;
    replaceText(doc.body);
    observeRoot(doc.body);
  };

  const translateIframes = () => {
    const frames = document.querySelectorAll("iframe");
    frames.forEach((frame) => {
      try {
        const doc = frame.contentDocument;
        translateDocument(doc);
      } catch (e) {
        // cross-origin frame; ignore
      }
    });
  };

  translateDocument(document);
  translateIframes();

  const iframeObserver = new MutationObserver(() => translateIframes());
  iframeObserver.observe(document.body, { childList: true, subtree: true });

  let runs = 0;
  const timer = setInterval(() => {
    translateDocument(document);
    translateIframes();
    runs += 1;
    if (runs > 12) clearInterval(timer);
  }, 700);
})();
</script>
""",
        unsafe_allow_html=True,
    )


def inject_selection_helper_script() -> None:
    """Tek tıkla seçimi belirginleştirmek için yardımcı JS."""
    st.markdown(
        """
<script>
(function() {
  const setHiddenValue = (value) => {
    const updateDoc = (doc) => {
      if (!doc) return;
      const input = doc.querySelector('input[aria-label="js_selected_node_id"]');
      if (!input) return;
      if (input.value !== value) {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    };
    updateDoc(document);
    try {
      if (window.parent && window.parent.document) {
        updateDoc(window.parent.document);
      }
    } catch (e) {
      // ignore
    }
  };

  const applySelectionHandlers = (doc) => {
    if (!doc || !doc.body || doc.__selectionHelper) return;
    doc.__selectionHelper = true;
    const clearSelection = () => {
      const selected = doc.querySelectorAll(".react-flow__node.manual-selected");
      selected.forEach((n) => n.classList.remove("manual-selected"));
      const rfSelectedNodes = doc.querySelectorAll(".react-flow__node.selected");
      rfSelectedNodes.forEach((n) => n.classList.remove("selected"));
      const rfSelectedEdges = doc.querySelectorAll(".react-flow__edge.selected");
      rfSelectedEdges.forEach((e) => e.classList.remove("selected"));
      setHiddenValue("");
    };

    const isInsideFlow = (target) => {
      return !!(target && target.closest && target.closest(".react-flow"));
    };

    const isControlArea = (target) => {
      return !!(
        target &&
        target.closest &&
        target.closest(".react-flow__controls, .react-flow__minimap, .react-flow__panel")
      );
    };

    const handleEvent = (e) => {
      const target = e && e.target ? e.target : null;
      if (isControlArea(target)) return;
      const node = target && target.closest ? target.closest(".react-flow__node") : null;
      const pane = target && target.closest ? target.closest(".react-flow__pane") : null;
      if (node) {
        const selected = doc.querySelectorAll(".react-flow__node.manual-selected");
        selected.forEach((n) => n.classList.remove("manual-selected"));
        node.classList.add("manual-selected");
        const nodeId = node.getAttribute("data-id") || (node.dataset ? node.dataset.id : "");
        if (nodeId) setHiddenValue(nodeId);
        return;
      }
      if (pane || isInsideFlow(target)) {
        clearSelection();
      }
    };

    doc.body.addEventListener("pointerdown", handleEvent, true);
    doc.body.addEventListener("click", handleEvent, true);
  };

  const applyToIframes = () => {
    const frames = document.querySelectorAll("iframe");
    frames.forEach((frame) => {
      try {
        applySelectionHandlers(frame.contentDocument);
      } catch (e) {
        // cross-origin frame; ignore
      }
    });
  };

  applySelectionHandlers(document);
  applyToIframes();

  const obs = new MutationObserver(() => applyToIframes());
  obs.observe(document.body, { childList: true, subtree: true });
})();
</script>
""",
        unsafe_allow_html=True,
    )


def inject_keyboard_shortcuts() -> None:
    """Klavye kısayolları (Ctrl+Z, Ctrl+Y, Delete, Ctrl+S)."""
    st.markdown(
        """
<script>
(function() {
  const findButton = (label) => {
    const buttons = Array.from(document.querySelectorAll("button"));
    return buttons.find((b) => (b.innerText || "").trim() === label);
  };

  const clickButton = (label) => {
    const btn = findButton(label);
    if (btn) btn.click();
  };

  document.addEventListener("keydown", (e) => {
    const tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || document.activeElement.isContentEditable) {
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      clickButton("Geri");
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      clickButton("İleri");
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      clickButton("Kaydet");
    }
    if (e.key === "Delete") {
      e.preventDefault();
      clickButton("Seçiliyi Sil");
    }
  });
})();
</script>
""",
        unsafe_allow_html=True,
    )


# =============================================================================
# Session State
# =============================================================================


def initialize_state() -> None:
    if "project_title" not in st.session_state:
        st.session_state.project_title = "Akış Şeması"

    if "user_mode" not in st.session_state:
        # Eski view_mode kayıtları ile uyumluluk
        legacy_mode = st.session_state.get("view_mode")
        if legacy_mode == "Basit":
            st.session_state.user_mode = "Basit"
        elif legacy_mode == "Uzman":
            st.session_state.user_mode = "Uzman"
        else:
            st.session_state.user_mode = DEFAULT_MODE

    if "direction" not in st.session_state:
        st.session_state.direction = DEFAULT_DIRECTION

    if "code_text" not in st.session_state:
        st.session_state.code_text = DEFAULT_CODE

    if "flow_state" not in st.session_state:
        parsed_state, error, direction = parse_mermaid(st.session_state.code_text)
        if parsed_state is None or error:
            # Fallback: tek düğüm
            nodes = [make_node("start", "Başla", "terminal", pos=(0, 0))]
            edges: List[StreamlitFlowEdge] = []
            st.session_state.flow_state = make_flow_state(nodes, edges)
        else:
            st.session_state.flow_state = parsed_state
            st.session_state.direction = direction
        sync_counters_from_state(st.session_state.flow_state)

    if "history" not in st.session_state:
        st.session_state.history = HistoryManager()
        st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="init")

    if "last_graph_hash" not in st.session_state:
        st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)

    if "last_code_hash" not in st.session_state:
        st.session_state.last_code_hash = text_hash(st.session_state.code_text)

    if "selected_node_id" not in st.session_state:
        st.session_state.selected_node_id = None

    if "selected_edge_id" not in st.session_state:
        st.session_state.selected_edge_id = None

    if "js_selected_node_id" not in st.session_state:
        st.session_state.js_selected_node_id = ""
    if "last_js_selected_node_id" not in st.session_state:
        st.session_state.last_js_selected_node_id = ""

    if "last_active_node_id" not in st.session_state:
        st.session_state.last_active_node_id = None

    if "node_counter" not in st.session_state:
        st.session_state.node_counter = 1

    if "edge_counter" not in st.session_state:
        st.session_state.edge_counter = 1

    if "last_auto_save" not in st.session_state:
        st.session_state.last_auto_save = 0

    if "recovery_shown" not in st.session_state:
        st.session_state.recovery_shown = False

    if "groq_api_key" not in st.session_state:
        st.session_state.groq_api_key = ""

    if not st.session_state.groq_api_key:
        env_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_APIKEY")
        secret_key = None
        try:
            secret_key = st.secrets.get("GROQ_API_KEY")  # type: ignore[attr-defined]
        except Exception:
            secret_key = None
        if secret_key:
            st.session_state.groq_api_key = str(secret_key)
        elif env_key:
            st.session_state.groq_api_key = str(env_key)
        else:
            autosave = load_autosave()
            if autosave and autosave.get("groq_api_key"):
                st.session_state.groq_api_key = str(autosave.get("groq_api_key"))

    if "ai_model" not in st.session_state:
        st.session_state.ai_model = "llama-3.3-70b-versatile"

    if "ai_mode" not in st.session_state:
        st.session_state.ai_mode = "Akış Şeması"
        autosave = load_autosave()
        if autosave and autosave.get("ai_mode"):
            st.session_state.ai_mode = str(autosave.get("ai_mode"))

    # Eski değerleri yeni etiketlere dönüştür
    if st.session_state.ai_mode == "Şema (Oklu)":
        st.session_state.ai_mode = "Akış Şeması"
    elif st.session_state.ai_mode == "Serbest (Bağımsız)":
        st.session_state.ai_mode = "Bağımsız Düğümler"

    if "ai_rate_limit_until" not in st.session_state:
        st.session_state.ai_rate_limit_until = 0

    if "ai_prompt_text" not in st.session_state:
        st.session_state.ai_prompt_text = ""

    if "ai_last_error" not in st.session_state:
        st.session_state.ai_last_error = ""

    # UI toggles
    if "show_code" not in st.session_state:
        st.session_state.show_code = True

    if "show_minimap" not in st.session_state:
        st.session_state.show_minimap = False

    if "show_controls" not in st.session_state:
        st.session_state.show_controls = True

    if "enable_context_menus" not in st.session_state:
        st.session_state.enable_context_menus = True

    if "show_grid" not in st.session_state:
        st.session_state.show_grid = True

    if "node_spacing" not in st.session_state:
        st.session_state.node_spacing = 70

    if "view_mode" not in st.session_state:
        st.session_state.view_mode = "Basit"

    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = DEFAULT_LAYOUT_MODE

    if "export_format" not in st.session_state:
        st.session_state.export_format = DEFAULT_EXPORT_FORMAT

    if "quick_export_format" not in st.session_state:
        st.session_state.quick_export_format = DEFAULT_EXPORT_FORMAT

    if "export_scale" not in st.session_state:
        st.session_state.export_scale = 2

    if "auto_validate" not in st.session_state:
        st.session_state.auto_validate = True

    if "show_rubric" not in st.session_state:
        st.session_state.show_rubric = True

    if "show_pseudocode" not in st.session_state:
        st.session_state.show_pseudocode = True

    if "selected_task" not in st.session_state:
        st.session_state.selected_task = ""

    if "task_check_fired" not in st.session_state:
        st.session_state.task_check_fired = False

    if "label_suggestion_index" not in st.session_state:
        st.session_state.label_suggestion_index = {}

    if "auto_connect" not in st.session_state:
        st.session_state.auto_connect = True

    if "global_node_colors_enabled" not in st.session_state:
        st.session_state.global_node_colors_enabled = False
    if "global_node_bg" not in st.session_state:
        st.session_state.global_node_bg = DEFAULT_GLOBAL_NODE_COLORS["bg"]
    if "global_node_border" not in st.session_state:
        st.session_state.global_node_border = DEFAULT_GLOBAL_NODE_COLORS["border"]
    if "global_node_text" not in st.session_state:
        st.session_state.global_node_text = DEFAULT_GLOBAL_NODE_COLORS["text"]

    if "auto_connect_fired" not in st.session_state:
        st.session_state.auto_connect_fired = False

    if "auto_connect_anchor" not in st.session_state:
        st.session_state.auto_connect_anchor = None

    if "pending_edge_id" not in st.session_state:
        st.session_state.pending_edge_id = None

    if "pending_edge_label" not in st.session_state:
        st.session_state.pending_edge_label = ""

    if "quick_node_label" not in st.session_state:
        st.session_state.quick_node_label = ""
    if "last_quick_node_id" not in st.session_state:
        st.session_state.last_quick_node_id = None

    if "export_png" not in st.session_state:
        st.session_state.export_png = None

    if "export_svg" not in st.session_state:
        st.session_state.export_svg = None

    if "export_pdf" not in st.session_state:
        st.session_state.export_pdf = None

    if "export_error" not in st.session_state:
        st.session_state.export_error = None

    if "quick_export_data" not in st.session_state:
        st.session_state.quick_export_data = None
    if "quick_export_name" not in st.session_state:
        st.session_state.quick_export_name = None
    if "quick_export_mime" not in st.session_state:
        st.session_state.quick_export_mime = None
    if "quick_export_error" not in st.session_state:
        st.session_state.quick_export_error = None
    if "last_quick_export_format" not in st.session_state:
        st.session_state.last_quick_export_format = None

    if "last_edge_ids" not in st.session_state:
        st.session_state.last_edge_ids = set()

    # Zoom persistence - viewport state
    if "viewport_zoom" not in st.session_state:
        st.session_state.viewport_zoom = 1.0
    if "viewport_x" not in st.session_state:
        st.session_state.viewport_x = 0.0
    if "viewport_y" not in st.session_state:
        st.session_state.viewport_y = 0.0

    # Koşullu auto-layout için düğüm sayısı takibi
    if "last_node_count" not in st.session_state:
        st.session_state.last_node_count = len(st.session_state.flow_state.nodes)
    if "force_layout_reset" not in st.session_state:
        st.session_state.force_layout_reset = False

    # Sayaçları mevcut düğümlere göre hizala (id çakışmasını önler)
    sync_counters_from_state(st.session_state.flow_state)


def apply_view_mode() -> None:
    """Geriye dönük uyumluluk için user_mode ayarlarını uygular."""
    mode = st.session_state.get("user_mode", DEFAULT_MODE)
    cfg = USER_MODES.get(mode, USER_MODES[DEFAULT_MODE])
    st.session_state.show_code = cfg["show_code"]
    st.session_state.show_minimap = cfg["show_minimap"]
    st.session_state.show_controls = cfg["show_controls"]
    st.session_state.enable_context_menus = cfg["enable_context_menus"]
    st.session_state.allowed_palette = cfg["palette"]
    st.session_state.allowed_exports = cfg["export_formats"]
    st.session_state.allow_edge_style = cfg["allow_edge_style"]
    if "show_templates" not in st.session_state:
        st.session_state.show_templates = cfg["show_templates"]
    if st.session_state.export_format not in st.session_state.allowed_exports:
        st.session_state.export_format = st.session_state.allowed_exports[0]
    if st.session_state.get("quick_export_format") not in st.session_state.allowed_exports:
        st.session_state.quick_export_format = st.session_state.allowed_exports[0]


# =============================================================================
# Seçim & Düzenleme
# =============================================================================


def sync_selection_from_js(flow_state: StreamlitFlowState) -> None:
    """JS tarafındaki tek tık seçimini session state'e yansıtır."""
    js_id = (st.session_state.get("js_selected_node_id") or "").strip()
    last_js = st.session_state.get("last_js_selected_node_id")
    if js_id == last_js:
        return
    st.session_state.last_js_selected_node_id = js_id
    st.session_state.js_selection_changed = True

    if not js_id:
        st.session_state.force_clear_selection = True
        st.session_state.selected_node_id = None
        st.session_state.selected_edge_id = None
        st.session_state.last_active_node_id = None
        if hasattr(flow_state, "selected_id"):
            try:
                flow_state.selected_id = None  # type: ignore[attr-defined]
            except Exception:
                pass
        return

    node_ids = {n.id for n in flow_state.nodes}
    if js_id in node_ids:
        st.session_state.selected_node_id = js_id
        st.session_state.selected_edge_id = None
        st.session_state.last_active_node_id = js_id


def apply_js_selection() -> None:
    """JS tarafındaki seçim değişimini anında uygula."""
    flow_state = st.session_state.get("flow_state")
    if flow_state is None:
        return
    sync_selection_from_js(flow_state)


def update_selection_from_state(flow_state: StreamlitFlowState) -> None:
    """Flow state'teki seçimi hızlıca session state'e aktar."""
    if st.session_state.get("force_clear_selection"):
        st.session_state.force_clear_selection = False
        st.session_state.selected_node_id = None
        st.session_state.selected_edge_id = None
        st.session_state.last_active_node_id = None
        if hasattr(flow_state, "selected_id"):
            try:
                flow_state.selected_id = None  # type: ignore[attr-defined]
            except Exception:
                pass
        return
    
    # Flow state'ten seçimi direkt al
    selected_id = getattr(flow_state, "selected_id", None)
    if not selected_id:
        return
    
    node_ids = {n.id for n in flow_state.nodes}
    edge_ids = {e.id for e in flow_state.edges}
    
    # Hızlı seçim - tek tıkla çalışsın
    if selected_id in node_ids:
        if st.session_state.selected_node_id != selected_id:
            st.session_state.selected_node_id = selected_id
            st.session_state.selected_edge_id = None
            st.session_state.last_active_node_id = selected_id
    elif selected_id in edge_ids:
        if st.session_state.selected_edge_id != selected_id:
            st.session_state.selected_edge_id = selected_id
            st.session_state.selected_node_id = None


def next_node_id() -> str:
    st.session_state.node_counter += 1
    return f"n{st.session_state.node_counter}"  # güvenli id


def next_edge_id(source: str, target: str) -> str:
    st.session_state.edge_counter += 1
    return f"e{st.session_state.edge_counter}_{source}_{target}"


def find_node(node_id: str) -> Optional[StreamlitFlowNode]:
    for n in st.session_state.flow_state.nodes:
        if n.id == node_id:
            return n
    return None


def find_edge(edge_id: str) -> Optional[StreamlitFlowEdge]:
    for e in st.session_state.flow_state.edges:
        if e.id == edge_id:
            return e
    return None


def is_position_free(pos: Tuple[float, float], nodes: List[StreamlitFlowNode]) -> bool:
    px, py = pos
    min_dx = 220.0
    min_dy = 130.0
    for n in nodes:
        x, y = get_node_pos(n)
        if abs(px - x) < min_dx and abs(py - y) < min_dy:
            return False
    return True


def next_free_position() -> Tuple[float, float]:
    nodes = st.session_state.flow_state.nodes
    if not nodes:
        return (0.0, 0.0)
    spacing_x = 260.0
    spacing_y = 160.0
    cols = 5
    max_rows = 50
    for row in range(max_rows):
        for col in range(cols):
            pos = (col * spacing_x, row * spacing_y)
            if is_position_free(pos, nodes):
                return pos
    # fallback: en sona ekle
    return (cols * spacing_x, max_rows * spacing_y)


def add_node(kind: str, label_override: Optional[str] = None, connect_from: Optional[str] = None) -> None:
    """Yeni düğüm ekler ve opsiyonel olarak mevcut düğüme bağlar.
    
    Args:
        kind: Düğüm tipi (start, end, process, decision, vb.)
        label_override: Özel etiket (None ise otomatik üretilir)
        connect_from: Bağlanacak kaynak düğüm ID'si
    
    Side Effects:
        - flow_state'e yeni düğüm eklenir
        - connect_from belirtilmişse yeni edge oluşturulur
        - Mermaid kodu güncellenir
        - History'ye kaydedilir
    """
    kind = kind if kind in NODE_KIND else "process"
    label = label_override or suggest_label_for_kind(kind)

    nid = next_node_id()

    # Konum: seçili düğümün altına; seçili yoksa boş alana
    pos = next_free_position()
    if connect_from:
        src_node = find_node(connect_from)
        if src_node is not None:
            x, y = get_node_pos(src_node)
            spacing_y = 160.0
            placed = False
            for i in range(6):
                candidate = (x, y + spacing_y * (i + 1))
                if is_position_free(candidate, st.session_state.flow_state.nodes):
                    pos = candidate
                    placed = True
                    break
            if not placed:
                pos = next_free_position()

    new_node = make_node(nid, label, kind, pos=pos)
    st.session_state.flow_state.nodes.append(new_node)

    # Otomatik bağla
    src_id = connect_from
    if src_id and src_id != nid:
        eid = next_edge_id(src_id, nid)
        label = ""
        src_node = find_node(src_id)
        if src_node is not None and get_node_kind(src_node) == "decision":
            # Karar düğümünden çıkan mevcut bağlantıları say
            existing_edges = [e for e in st.session_state.flow_state.edges if e.source == src_id]
            existing_labels = [get_edge_label(e).lower() for e in existing_edges]
            
            # İlk dal: "Evet", İkinci dal: "Hayır", 3. ve sonrası: boş
            if len(existing_edges) == 0:
                label = "Evet"
            elif len(existing_edges) == 1:
                # Eğer ilk dalda zaten "Evet" varsa ikinci dal "Hayır", yoksa kontrol et
                if any("evet" in lbl for lbl in existing_labels):
                    label = "Hayır"
                else:
                    # İlk dal "Evet" değilse, ikinci dala da "Hayır" yazma, boş bırak
                    label = ""
            else:
                # 3. ve sonraki dallar için etiket yok (boş)
                label = ""
        
        st.session_state.flow_state.edges.append(make_edge(eid, src_id, nid, label=label, edge_type="smoothstep"))

    st.session_state.last_active_node_id = nid

    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action=f"add_node({kind})")


def add_edge(
    source: str,
    target: str,
    label: str = "",
    edge_type: str = "smoothstep",
    variant: str = "solid",
    color: Optional[str] = None,
) -> None:
    if source == target:
        st.warning("Kaynak ve hedef aynı olamaz.")
        return
    if find_node(source) is None or find_node(target) is None:
        st.warning("Kaynak veya hedef düğüm bulunamadı.")
        return
    if any(e.source == source and e.target == target and (get_edge_label(e) or "") == (label or "") for e in st.session_state.flow_state.edges):
        st.info("Bu bağlantı zaten mevcut.")
        return

    eid = next_edge_id(source, target)
    st.session_state.flow_state.edges.append(
        make_edge(eid, source, target, label=label, edge_type=edge_type, variant=variant, color=color)
    )
    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="add_edge")


def delete_node(node_id: str) -> None:
    nodes = st.session_state.flow_state.nodes
    edges = st.session_state.flow_state.edges
    st.session_state.flow_state.nodes = [n for n in nodes if n.id != node_id]
    st.session_state.flow_state.edges = [e for e in edges if e.source != node_id and e.target != node_id]
    if st.session_state.last_active_node_id == node_id:
        st.session_state.last_active_node_id = None
    if st.session_state.get("auto_connect_anchor") == node_id:
        st.session_state.auto_connect_anchor = None
    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="delete_node")


def delete_edge(edge_id: str) -> None:
    edges = st.session_state.flow_state.edges
    st.session_state.flow_state.edges = [e for e in edges if e.id != edge_id]
    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="delete_edge")


def delete_selected() -> None:
    """Seçili düğüm veya bağlantıyı siler.
    
    Seçili düğüm varsa düğümü ve ona bağlı tüm edge'leri siler.
    Seçili edge varsa sadece edge'i siler.
    Hiçbiri seçili değilse kullanıcıya uyarı gösterir.
    
    Side Effects:
        - Seçili öğe flow_state'ten kaldırılır
        - Session state'teki seçim temizlenir
        - Toast bildirimi gösterilir
        - Mermaid kodu güncellenir
        - History'ye kaydedilir
    """
    node_id = st.session_state.get("selected_node_id")
    edge_id = st.session_state.get("selected_edge_id")
    if node_id:
        delete_node(node_id)
        st.session_state.selected_node_id = None
        st.session_state.selected_edge_id = None
        toast_warning("Seçili düğüm silindi.")
        return
    if edge_id:
        delete_edge(edge_id)
        st.session_state.selected_node_id = None
        st.session_state.selected_edge_id = None
        toast_warning("Seçili bağlantı silindi.")
        return
    toast_warning("Silmek için bir düğüm veya bağlantı seçin.")


def update_node(
    node_id: str,
    new_label: str,
    new_kind: str,
    width: int,
    source_position: str,
    target_position: str,
    colors: Optional[Dict[str, str]] = None,
) -> None:
    """Mevcut düğümü günceller.
    
    Args:
        node_id: Güncellenecek düğümün ID'si
        new_label: Yeni etiket metni
        new_kind: Yeni düğüm tipi (start, end, process, vb.)
        width: Düğüm genişliği (piksel)
        source_position: Çıkış konnektörü konumu (top, right, bottom, left)
        target_position: Giriş konnektörü konumu
    
    Side Effects:
        - Düğümün data, style ve handle pozisyonları güncellenir
        - Mermaid kodu yeniden oluşturulur
        - History'ye kaydedilir
    """
    n = find_node(node_id)
    if n is None:
        st.warning("Düğüm bulunamadı")
        return

    new_kind = new_kind if new_kind in NODE_KIND else get_node_kind(n)
    new_label = (new_label or "").strip() or n.id

    # data
    data = getattr(n, "data", None) or {}
    data["label"] = new_label
    data["kind"] = new_kind
    data["content"] = node_markdown(new_label, new_kind)
    existing_colors = normalize_color_overrides(data.get("colors") if isinstance(data, dict) else None)
    if colors is None:
        color_overrides = existing_colors
    else:
        color_overrides = normalize_color_overrides(colors)
        if color_overrides:
            data["colors"] = color_overrides
        else:
            data.pop("colors", None)
    n.data = data  # type: ignore[attr-defined]

    # style
    n.style = node_style(new_kind, width=width, colors=color_overrides)  # type: ignore[attr-defined]

    # handles
    if hasattr(n, "source_position"):
        n.source_position = source_position  # type: ignore[attr-defined]
    if hasattr(n, "target_position"):
        n.target_position = target_position  # type: ignore[attr-defined]

    normalize_state(st.session_state.flow_state)
    if st.session_state.get("layout_mode") == "Otomatik (Ağaç)":
        st.session_state.force_layout_reset = True
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="update_node")


def update_edge(
    edge_id: str,
    label: str,
    edge_type: str,
    source: str,
    target: str,
    variant: str = "solid",
    color: Optional[str] = None,
) -> None:
    e = find_edge(edge_id)
    if e is None:
        st.warning("Bağlantı bulunamadı")
        return
    if source == target:
        st.warning("Kaynak ve hedef aynı olamaz")
        return

    e.source = source  # type: ignore[attr-defined]
    e.target = target  # type: ignore[attr-defined]
    e.label = label or ""  # type: ignore[attr-defined]
    # streamlit-flow edge paramı edge_type ama objede type olabilir
    if hasattr(e, "edge_type"):
        e.edge_type = edge_type  # type: ignore[attr-defined]
    else:
        e.type = edge_type  # type: ignore[attr-defined]
    if getattr(e, "data", None) is None:
        e.data = {}  # type: ignore[attr-defined]
    e.data["variant"] = variant  # type: ignore[attr-defined]
    if color:
        e.data["color"] = color  # type: ignore[attr-defined]
    else:
        if "color" in e.data:
            del e.data["color"]
    style, marker = edge_style_for_type(edge_type, variant, color_override=color)
    e.style = style  # type: ignore[attr-defined]
    e.marker_end = marker  # type: ignore[attr-defined]

    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="update_edge")


def reverse_edge(edge_id: str) -> None:
    e = find_edge(edge_id)
    if e is None:
        return
    e.source, e.target = e.target, e.source  # type: ignore[attr-defined]
    normalize_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="reverse_edge")


def apply_quick_node_label() -> None:
    node_id = st.session_state.get("selected_node_id")
    if not node_id:
        return
    node = find_node(node_id)
    if node is None:
        return
    label = (st.session_state.get("quick_node_label") or "").strip()
    label = label or node_id
    kind = get_node_kind(node)
    width = parse_style_width(getattr(node, "style", {}), 160)
    src_pos, tgt_pos = default_handle_positions(st.session_state.direction)
    update_node(node_id, label, kind, width, src_pos, tgt_pos)


def apply_edge_label_input() -> None:
    edge_id = st.session_state.get("selected_edge_id")
    if not edge_id:
        return
    edge = find_edge(edge_id)
    if edge is None:
        return
    label = (st.session_state.get("edge_label_input") or "").strip()
    update_edge(
        edge_id,
        label,
        get_edge_type(edge),
        edge.source,
        edge.target,
        get_edge_variant(edge),
        color=get_edge_color(edge),
    )


# =============================================================================
# Sidebar (sol)
# =============================================================================


def render_header_bar() -> None:
    """Üst başlık alanı: uygulama adı."""
    st.markdown(
        f"<h2 style='margin-top:0;margin-bottom:0.1rem;'>{APP_TITLE}</h2>",
        unsafe_allow_html=True,
    )
    st.caption(APP_CAPTION)


def render_view_mode_panel(container: st.delta_generator.DeltaGenerator) -> None:
    container.markdown("### Akış Şeması Görünümü")
    current_mode = st.session_state.get("user_mode", DEFAULT_MODE)
    mode = container.radio(
        "Görünüm Seç",
        list(USER_MODES.keys()),
        index=list(USER_MODES.keys()).index(current_mode) if current_mode in USER_MODES else 0,
        horizontal=True,
        label_visibility="collapsed",
    )
    if mode != st.session_state.user_mode:
        st.session_state.user_mode = mode
        apply_view_mode()
        st.rerun()


def render_ai_panel(container: st.delta_generator.DeltaGenerator) -> None:
    """Sidebar'da AI Asistanı panelini gösterir."""
    with container.expander("✨ AI Asistanı (Metinden Şemaya)", expanded=True):
        st.caption("🚀 Groq ile metinden şema üretimi")
        container.info(
            "Akış Şeması: Oklarla bağlı akış üretir. Bağımsız Düğümler: Ok çizmez, tipli kutular üretir.",
            icon="ℹ️",
        )
        st.caption("API anahtarını kimseyle paylaşmayın.")

        with container.expander("API Anahtarı Nasıl Alınır?", expanded=False):
            container.markdown(
                "1. `console.groq.com/keys` adresine git\n"
                "2. `API Anahtarı Oluştur` butonuna tıkla\n"
                "3. `gsk_` ile başlayan anahtarı kopyalayıp aşağıya yapıştır"
            )
        
        col_key, col_clear = st.columns([8, 1])
        with col_key:
            api_key = st.text_input(
                "Groq API Key (gsk_ ile başlar)",
                value=st.session_state.groq_api_key,
                type="password",
                placeholder="gsk_...",
                help="Yukarıdaki adımları takip ederek API anahtarınızı alın",
            )
            st.session_state.groq_api_key = api_key
        with col_clear:
            if st.button("🗑️", help="Kaydedilmiş API anahtarını sil", use_container_width=True):
                st.session_state.groq_api_key = ""
                auto_save_to_file()
                st.rerun()

        prompt = st.text_area(
            "Akış Tanımı",
            placeholder="Konu + amaç + 4-7 adım + 1 karar yazın (ör. okula gidiş).",
            height=110,
            help="Kısa ve net yazın: konu, amaç, ana adımlar ve kararlar. Gereksiz adım eklemeyin.",
            key="ai_prompt_text",
        )
        prompt = st.session_state.ai_prompt_text
        
        if st.session_state.get("show_templates", False):
            with container.expander("🧩 İdeal Tanım Şablonu", expanded=False):
                container.caption("En iyi sonuç için şu yapıyı kullan: konu + amaç + ana adımlar + kararlar + giriş/çıkış.")
                template = (
                    "Konu: (kısa başlık)\n"
                    "Amaç: (hedef)\n"
                    "Başlangıç: (tetikleyici olay)\n"
                    "Ana Adımlar: adım1; adım2; adım3; ...\n"
                    "Kararlar: soru? -> Evet: ... / Hayır: ...\n"
                    "Girişler: (alınan bilgiler)\n"
                    "Çıkışlar: (üretilen sonuç)\n"
                    "Notlar: (özel şartlar / istisna)"
                )
                container.code(template, language="text")
                col_t1, col_t2 = container.columns(2)
                with col_t1:
                    if col_t1.button("Şablonu Yapıştır", use_container_width=True, key="paste_prompt_template"):
                        st.session_state.ai_prompt_text = template
                        st.rerun()
                with col_t2:
                    sample = (
                        "Konu: Okula gidiş\n"
                        "Amaç: Okula zamanında varmak\n"
                        "Başlangıç: Alarm çaldı\n"
                        "Ana Adımlar: Uyan; Hazırlan; Kahvaltı yap; Çantayı al\n"
                        "Kararlar: Servis var mı? -> Evet: Servise bin / Hayır: Yürüyerek git\n"
                        "Girişler: Saat, hava durumu\n"
                        "Çıkışlar: Okula varıldı\n"
                        "Notlar: Geç kalırsam hızlı rota"
                    )
                    if col_t2.button("Örnek Doldur", use_container_width=True, key="fill_prompt_sample"):
                        st.session_state.ai_prompt_text = sample
                        st.rerun()
        
        mode_options = ["Akış Şeması", "Bağımsız Düğümler"]
        ai_mode = st.radio(
            "Oluşturma Modu",
            mode_options,
            index=mode_options.index(st.session_state.ai_mode) if st.session_state.ai_mode in mode_options else 0,
            horizontal=True,
        )
        st.session_state.ai_mode = ai_mode

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⚡ AI Üret", use_container_width=True, type="primary"):
                if not prompt.strip():
                    toast_warning("Lütfen bir tanım girin.")
                elif not api_key.strip():
                    toast_warning("Lütfen Groq API Key girin.")
                else:
                    now = int(time.time())
                    limit_until = int(st.session_state.get("ai_rate_limit_until", 0) or 0)
                    if now < limit_until:
                        toast_warning(f"Limit nedeniyle bekleyin: {limit_until - now} sn")
                        return
                    if st.session_state.ai_mode == "Bağımsız Düğümler":
                        labels = generate_free_nodes_with_ai(prompt, api_key, "llama-3.3-70b-versatile")
                        if labels:
                            apply_free_nodes(labels, name="AI Serbest")
                        else:
                            toast_warning("AI bağımsız düğüm üretimi başarısız oldu; şablon uygulanmadı.")
                    else:
                        # Akış Şeması Modu
                        with st.spinner("🤖 AI akış şeması oluşturuyor..."):
                            mermaid_code = generate_flow_with_ai(prompt, api_key, "llama-3.3-70b-versatile")
                        
                        if mermaid_code:
                            # Şemayı uygula ve ekrana yansıt
                            apply_ai_flow_template(mermaid_code, prompt, name="AI Akış Şeması")
                        else:
                            toast_warning("AI akış şeması üretimi başarısız oldu; şablon uygulanmadı.")
        
        with col2:
            if st.button("🗑️ Tümünü Temizle", use_container_width=True, help="Tüm düğümleri siler, sıfırdan başlar"):
                # Tek başlangıç düğümü ile temiz başlangıç
                empty_code = """flowchart TD
    start([Başla])
""".strip()
                # Direkt state'i sıfırla
                st.session_state.flow_state = make_flow_state(
                    [make_node("start", "Başla", "terminal", pos=(250, 100))],
                    []
                )
                st.session_state.code_text = empty_code
                st.session_state.direction = "TD"
                st.session_state.node_counter = 1
                st.session_state.edge_counter = 1
                st.session_state.selected_node_id = None
                st.session_state.selected_edge_id = None
                st.session_state.history = HistoryManager()
                st.session_state.history.push(empty_code, st.session_state.flow_state, action="clear")
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                st.session_state.last_code_hash = text_hash(empty_code)
                toast_success("✨ Tüm düğümler temizlendi!")
                st.rerun()


def render_quick_export_panel(container: st.delta_generator.DeltaGenerator) -> None:
    container.markdown("### 📤 Dışa Aktar")
    allowed = st.session_state.get("allowed_exports", ["Mermaid", "PNG", "SVG", "JSON", "PDF"])
    quick_format = container.selectbox("Biçim", allowed, key="quick_export_format")

    if quick_format != st.session_state.get("last_quick_export_format"):
        st.session_state.quick_export_data = None
        st.session_state.quick_export_name = None
        st.session_state.quick_export_mime = None
        st.session_state.quick_export_error = None
        st.session_state.last_quick_export_format = quick_format

    if quick_format in ("PNG", "PDF"):
        container.slider(f"{quick_format} görsel kalite (ölçek)", 1, 4, key="export_scale")

    if quick_format in ("PNG", "SVG", "PDF") and requests is None:
        container.info("SVG/PNG/PDF oluşturmak için `requests` gerekli. Kurulum: `pip install requests`")
    if quick_format == "PDF" and canvas is None:
        container.info("PDF için `reportlab` gerekli. Kurulum: `pip install reportlab`")

    can_prepare = True
    if quick_format in ("PNG", "SVG", "PDF") and requests is None:
        can_prepare = False
    if quick_format == "PDF" and canvas is None:
        can_prepare = False

    col_a, col_b = container.columns([1, 1])
    with col_a:
        if st.button("Hazırla", use_container_width=True, key="quick_export_prepare_sidebar", disabled=not can_prepare):
            try:
                st.session_state.quick_export_error = None
                latest_code = refresh_code_from_state()
                export_code = build_export_code()
                if quick_format == "Mermaid":
                    st.session_state.quick_export_data = latest_code
                    st.session_state.quick_export_name = safe_filename(st.session_state.project_title, ".mmd")
                    st.session_state.quick_export_mime = "text/plain"
                    toast_success("Mermaid kodu hazırlandı")
                elif quick_format == "JSON":
                    payload = export_json_payload(st.session_state.flow_state)
                    st.session_state.quick_export_data = json.dumps(payload, ensure_ascii=False, indent=2)
                    st.session_state.quick_export_name = safe_filename(st.session_state.project_title, ".json")
                    st.session_state.quick_export_mime = "application/json"
                    toast_success("JSON hazırlandı")
                elif quick_format == "SVG":
                    with st.spinner("🎨 SVG oluşturuluyor..."):
                        st.session_state.quick_export_data = export_svg_via_mermaid_ink(export_code)
                        st.session_state.quick_export_name = safe_filename(st.session_state.project_title, ".svg")
                        st.session_state.quick_export_mime = "image/svg+xml"
                    toast_success("SVG hazırlandı")
                elif quick_format == "PDF":
                    with st.spinner("📄 PDF oluşturuluyor..."):
                        checklist = [
                            "Başla ve Bitir düğümleri var",
                            "Giriş/Çıkış düğümü var",
                            "Karar düğümü doğru kullanılmış",
                            "Bağlantı etiketleri mevcut",
                            "Döngü kontrolü yapılmış",
                        ]
                        st.session_state.quick_export_data = export_pdf_report(
                            export_code,
                            st.session_state.project_title,
                            checklist,
                            scale=st.session_state.export_scale,
                        )
                        st.session_state.quick_export_name = safe_filename(st.session_state.project_title, ".pdf")
                        st.session_state.quick_export_mime = "application/pdf"
                    toast_success("PDF hazırlandı")
                else:
                    with st.spinner("🖼️ PNG oluşturuluyor..."):
                        st.session_state.quick_export_data = export_png_via_mermaid_ink(
                            export_code, scale=st.session_state.export_scale
                        )
                        st.session_state.quick_export_name = safe_filename(st.session_state.project_title, ".png")
                        st.session_state.quick_export_mime = "image/png"
                    toast_success("PNG hazırlandı")
            except Exception as exc:
                st.session_state.quick_export_error = str(exc)
                toast_error(f"Dışa aktarma hatası: {exc}")

    with col_b:
        if st.session_state.get("quick_export_data"):
            st.download_button(
                "İndir",
                data=st.session_state.quick_export_data,
                file_name=st.session_state.get("quick_export_name") or "export",
                mime=st.session_state.get("quick_export_mime") or "application/octet-stream",
                use_container_width=True,
            )
        else:
            st.caption("Hazırla → İndir")

    if st.session_state.get("quick_export_error"):
        container.error(st.session_state.quick_export_error)


def render_settings_panel(container: st.delta_generator.DeltaGenerator) -> None:
    container.subheader("⚙️ Ayarlar")
    container.caption("Yön, yerleşim ve hizalama seçenekleri.")

    prev_spacing = st.session_state.get("node_spacing", 80)
    prev_layout_mode = st.session_state.get("layout_mode", DEFAULT_LAYOUT_MODE)

    current_label = next(
        (k for k, v in DIRECTION_LABELS.items() if v == st.session_state.direction),
        "Yukarıdan Aşağı (TD)",
    )
    new_label = container.selectbox(
        "Akış Yönü",
        list(DIRECTION_LABELS.keys()),
        index=list(DIRECTION_LABELS.keys()).index(current_label),
    )
    new_dir = DIRECTION_LABELS[new_label]
    if new_dir != st.session_state.direction:
        st.session_state.direction = new_dir
        if st.session_state.layout_mode == "Otomatik (Ağaç)":
            st.session_state.force_layout_reset = True
        sync_code_text(generate_mermaid(st.session_state.flow_state, new_dir))

    layout_mode = container.selectbox("Yerleşim", LAYOUT_MODES, index=LAYOUT_MODES.index(st.session_state.layout_mode))
    if layout_mode != st.session_state.layout_mode:
        st.session_state.layout_mode = layout_mode
        if st.session_state.layout_mode == "Otomatik (Ağaç)":
            st.session_state.force_layout_reset = True

    container.toggle(
        "Şablon Paneli",
        key="show_templates",
        help="Şablon kütüphanesi ve örnek şablon alanını gösterir.",
    )

    auto_connect = container.toggle("Tıkla‑Bağla (otomatik)", key="auto_connect")
    if not auto_connect:
        st.session_state.auto_connect_anchor = None
    container.toggle("Izgara görünümü", key="show_grid")
    container.toggle(
        "Izgara hizalama",
        key="enable_grid_snap",
        help="Düğümleri 20px ızgaraya otomatik hizalar",
    )
    container.slider("Düğüm aralığı", 40, 120, key="node_spacing")
    if st.session_state.get("layout_mode") == "Otomatik (Ağaç)":
        if st.session_state.get("node_spacing") != prev_spacing:
            st.session_state.force_layout_reset = True
        if prev_layout_mode != st.session_state.get("layout_mode"):
            st.session_state.force_layout_reset = True

    container.markdown("---")
    container.markdown("**Global Düğüm Renkleri**")
    container.caption("Açıkken tüm düğümler tek bir renk paletini kullanır.")
    use_global = container.toggle("Global renkleri etkinleştir", key="global_node_colors_enabled")
    if use_global:
        container.color_picker("Arka Plan (Global)", key="global_node_bg")
        container.color_picker("Kenarlık (Global)", key="global_node_border")
        container.color_picker("Yazı (Global)", key="global_node_text")

    # Grid görünümünü anlık kontrol et
    if not st.session_state.get("show_grid", True):
        container.markdown(
            "<style>.react-flow__pane{background:none !important;}</style>",
            unsafe_allow_html=True,
        )


def render_help_panel(container: st.delta_generator.DeltaGenerator) -> None:
    container.subheader("📚 Kılavuz")
    container.caption("Akış şeması düğümleri ve arayüz kullanımı.")

    container.info(
        "Hızlı Başlangıç: 1) Başla düğümünü seç. 2) Üst paletten adımları ekle. "
        "3) Karar düğümünde Evet/Hayır etiketlerini kontrol et."
    )

    exp_nodes = container.expander("🔷 Düğüm Tipleri ve Kullanımları", expanded=True)
    exp_nodes.markdown(
            """
<div class="help-small">
<strong>🟢 Başla / Bitir</strong><br/>
• Algoritmanın başlangıç ve bitiş noktalarını gösterir.<br/>
• Her akış şeması <strong>bir Başla</strong> ile başlar, <strong>bir veya daha fazla Bitir</strong> ile sona erer.<br/>
• Örnek: "Başla" → algoritmanın ilk adımı<br/>
<br/>
<strong>📥 Giriş/Çıkış</strong><br/>
• Kullanıcıdan veri almak veya ekrana sonuç yazdırmak için kullanılır.<br/>
• Giriş: "sayı oku", "isim al"<br/>
• Çıkış: "sonucu yaz", "mesaj göster"<br/>
<br/>
<strong>✍️ Manuel Giriş</strong><br/>
• Kullanıcıdan elle/klavye ile veri alınan adımlar.<br/>
• Örnek: "elle değer gir", "form doldur"<br/>
<br/>
<strong>🖥️ Görüntü</strong><br/>
• Ekranda görüntülenen çıktı veya sonuç.<br/>
• Örnek: "grafiği göster", "ekranda listele"<br/>
<br/>
<strong>⚙️ İşlem</strong><br/>
• Hesaplama, atama, matematiksel işlemler için kullanılır.<br/>
• Örnek: "toplam = a + b", "sayac = sayac + 1", "sonuç = x * 2"<br/>
<br/>
<strong>📄 Belge</strong><br/>
• Tek bir doküman/çıktı üretimi için kullanılır.<br/>
• Örnek: "raporu yazdır", "fatura oluştur"<br/>
<br/>
<strong>📑 Çoklu Belgeler</strong><br/>
• Birden fazla dokümanı temsil eder.<br/>
• Örnek: "evrak seti hazırla"<br/>
<br/>
<strong>❓ Karar</strong><br/>
• Koşullu durumlar için kullanılır (eğer/değilse).<br/>
• Baklava şeklinde gösterilir, iki çıkışı vardır: Evet/Hayır veya Doğru/Yanlış<br/>
• Örnek: "sayı > 0 ?", "not >= 50 ?", "şifre doğru mu?"<br/>
<br/>
<strong>🔻 Birleştir</strong><br/>
• Birden fazla akışı tek noktada toplar.<br/>
• Örnek: "sonraki adıma birleş"<br/>
<br/>
<strong>✋ Manuel İşlem</strong><br/>
• Otomatik olmayan, manuel yapılan adımlar.<br/>
• Örnek: "belgeyi imzala", "fiziksel kontrol yap"<br/>
<br/>
<strong>🔁 Döngü</strong><br/>
• Tekrarlayan işlemler için kullanılır.<br/>
• Örnek: "i = 1'den 10'a kadar", "sayac < 100 olduğu sürece"<br/>
<br/>
<strong>🔧 Alt Süreç</strong><br/>
• Fonksiyon çağrısı veya alt algoritma için kullanılır.<br/>
• Örnek: "faktöriyel_hesapla()", "asal_kontrol()"<br/>
<br/>
<strong>💾 Veritabanı</strong><br/>
• Veri saklama veya veri tabanı işlemleri için kullanılır.<br/>
• Örnek: "veritabanına kaydet", "kayıtları oku"<br/>
<br/>
<strong>🗃️ Veri Deposu</strong><br/>
• Kalıcı veri saklama (dosya/medya/arşiv).<br/>
• Örnek: "dosyaya kaydet", "arşive yaz"<br/>
<br/>
<strong>🧠 Dahili Depo</strong><br/>
• Bellek içi/geçici saklama adımları.<br/>
• Örnek: "RAM'e al", "önbelleğe yaz"<br/>
<br/>
<strong>📼 Bant Veri</strong><br/>
• Sıralı erişimli saklama (manyetik bant).<br/>
• Örnek: "bant arşivine yaz"<br/>
<br/>
<strong>🔗 Bağlantı</strong><br/>
• Sayfa geçişleri veya uzak bağlantılar için kullanılır.<br/>
• Karmaşık akışlarda şemayı düzenli tutmaya yarar.<br/>
<br/>
<strong>📝 Not</strong><br/>
• Açıklama veya not eklemek için kullanılır.<br/>
• Algoritmanın mantığını açıklamak için faydalıdır.<br/>
<br/>
<strong>💡 Fonksiyon</strong><br/>
• Özel fonksiyon tanımları için kullanılır.<br/>
• Örnek: "hesapla(x, y)", "doğrula(şifre)"<br/>
</div>
""",
            unsafe_allow_html=True,
        )

    exp_ui = container.expander("🧭 Arayüz ve Kullanım", expanded=False)
    exp_ui.markdown(
            """
<div class="help-small">
<strong>Sol Menü (Proje & Dışa Aktar)</strong><br/>
• Akış Şeması Görünümü: Basit / Uzman modu.<br/>
• Dışa Aktar: Mermaid, PNG, SVG, JSON, PDF hazırlayıp indir.<br/>
• Proje Yönetimi: Proje adı, kaydet/yeni, dosya yükle.<br/>
• Örnek akışlardan ilham alarak kendi şemanızı oluşturun.<br/>
• Uzman modunda ek araçlar: Rubrik, doğrulama, kontrol listesi.<br/>
<br/>
<strong>Sağ Menü (Düğüm / Bağlantı / Kod / Ayarlar)</strong><br/>
• Düğüm: Seçili düğümün metni, tipi, boyutu.<br/>
• Bağlantı: Bağlantı metni, çizgi tipi, rengi, yönü.<br/>
• Kod: Mermaid kodu görüntüle/düzenle.<br/>
• Ayarlar: Akış yönü, yerleşim, ızgara hizalama.<br/>
<br/>
<strong>Tuval Kullanımı</strong><br/>
• Düğüme tek tıkla seç, kenarlığı kesik çizgi olur.<br/>
• Boş alana tıklarsan seçim kalkar.<br/>
• Seçili düğüm varken üst paletten yeni düğüm eklersen otomatik bağlanır.<br/>
• Seçim yoksa yeni düğüm bağımsız oluşturulur.<br/>
<br/>
<strong>Hızlı İş Akışı</strong><br/>
• Üst paletten istediğiniz düğüme tıklayın.<br/>
• Eğer bir düğüm seçili ise, yeni düğüm ona otomatik bağlanır.<br/>
• Hiçbir düğüm seçili değilse, bağımsız düğüm oluşturulur.<br/>
<br/>
<strong>Düğüm Düzenleme</strong><br/>
• Düğüme tıklayarak seçin (kenarlığı kesik çizgi olur).<br/>
• Sağ paneldeki "Düğüm" sekmesinden metni, tipini ve boyutunu değiştirin.<br/>
• "⚡ Düğüm Metni (Hızlı)" kutusuna yazıp Enter'a basarak hızlıca güncelleyin.<br/>
<br/>
<strong>Bağlantı Oluşturma</strong><br/>
• Bir düğümden diğerine sürükleyerek bağlantı çizin.<br/>
• Yeni bağlantı eklendiğinde "Yeni Bağlantı Etiketi" ekranı çıkar.<br/>
• İsterseniz etiket yazın (örn: "Evet", "Hayır"), isterseniz boş bırakın.<br/>
• "Kaydet" veya "Atla" butonuna tıklayın.<br/>
<br/>
<strong>Sürükleme ve Yerleştirme</strong><br/>
• Düğümleri sürükleyerek istediğiniz yere taşıyın.<br/>
• Ayarlar sekmesinden "Otomatik (Ağaç)" yerleşim modunu seçerek düzeni otomatik hizalayın.<br/>
<br/>
<strong>Silme ve Geri Alma</strong><br/>
• Düğüm veya bağlantı seçip "🗑️ Seçiliyi Sil" butonuna basın.<br/>
• "⏪ Geri" ve "⏩ İleri" butonlarıyla işlemleri geri alabilirsiniz.<br/>
</div>
""",
            unsafe_allow_html=True,
        )


def render_sidebar() -> None:
    with st.sidebar:
        render_header_bar()
        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        render_view_mode_panel(st)
        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        is_basic = st.session_state.get("user_mode", DEFAULT_MODE) == "Basit"

        with st.expander("📁 Proje Yönetimi", expanded=True):
            st.text_input("Proje Adı", key="project_title")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Kaydet", use_container_width=True, type="primary"):
                    fn = safe_filename(st.session_state.project_title, ".mmd")
                    Path(fn).write_text(st.session_state.code_text, encoding="utf-8")
                    toast_success(f"Kaydedildi: {fn}")
            with col_b:
                if st.button("Yeni", use_container_width=True):
                    apply_template(DEFAULT_CODE, name="Yeni")

            uploaded = st.file_uploader(
                "Dosya Yükle (.mmd/.json)",
                type=["mmd", "txt", "json"],
                accept_multiple_files=False,
            )
            if uploaded is not None:
                if st.button("Yüklenen Dosyayı Aç", use_container_width=True):
                    try:
                        raw = uploaded.read()
                        if uploaded.name.lower().endswith(".json"):
                            data = json.loads(raw.decode("utf-8"))
                            state, err = import_json_payload(data)
                            if state is None:
                                toast_error(err)
                            else:
                                st.session_state.flow_state = state
                                st.session_state.direction = str(data.get("direction") or st.session_state.direction)
                                st.session_state.project_title = str(data.get("title") or st.session_state.project_title)
                                sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
                                sync_counters_from_state(st.session_state.flow_state)
                                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                                st.session_state.last_code_hash = text_hash(st.session_state.code_text)
                                st.session_state.history.push(
                                    st.session_state.code_text, st.session_state.flow_state, action="json_import"
                                )
                                toast_success("JSON proje yüklendi")
                                st.rerun()
                        else:
                            try:
                                content = raw.decode("utf-8")
                            except Exception:
                                content = raw.decode("utf-8", errors="replace")
                            apply_template(content, name=uploaded.name)
                    except Exception as exc:
                        toast_error(f"Dosya yüklenemedi: {exc}")

        if st.session_state.get("show_templates", False):
            with st.expander("🧩 Şablon Kütüphanesi", expanded=True):
                st.text_input("Şablon Ara", key="template_search", placeholder="Örn: döngü, karar, sistem")
                search = (st.session_state.get("template_search") or "").strip().lower()
                tmpl_names = list(TEMPLATES.keys())
                if search:
                    tmpl_names = [
                        name
                        for name in tmpl_names
                        if search in name.lower()
                        or search in TEMPLATES[name]["description"].lower()
                    ]
                if not tmpl_names:
                    st.info("Arama kriterine uygun şablon bulunamadı.")
                else:
                    tmpl_name = st.selectbox(
                        "Şablon Seç",
                        tmpl_names,
                        format_func=lambda x: f"{x} — {TEMPLATES[x]['description']}",
                    )
                    if st.button("Şablonu Uygula", use_container_width=True):
                        apply_template(TEMPLATES[tmpl_name]["code"], name=tmpl_name)

        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        render_ai_panel(st)
        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        if not is_basic:
            with st.expander("🧰 Araçlar", expanded=False):
                st.toggle("Otomatik doğrula", key="auto_validate")
                st.toggle("Rubrik puanını göster", key="show_rubric")
                st.toggle("Sözde Kod paneli", key="show_pseudocode")
                st.markdown("**Kontrol Listesi**")
                nodes = st.session_state.flow_state.nodes
                has_start = any(is_start_node(n) for n in nodes)
                has_end = any(is_end_node(n) for n in nodes)
                has_io = any(get_node_kind(n) == "io" for n in nodes)
                has_decision = any(get_node_kind(n) == "decision" for n in nodes)
                st.checkbox("Başla düğümü", value=has_start, disabled=True)
                st.checkbox("Bitir düğümü", value=has_end, disabled=True)
                st.checkbox("Giriş/Çıkış düğümü", value=has_io, disabled=True)
                st.checkbox("Karar düğümü", value=has_decision, disabled=True)

            with st.expander("✅ Kontrol / Hata Bul", expanded=False):
                render_control_panel(st, compact=True)

        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        render_quick_export_panel(st)

        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        st.markdown(
            '<a class="suggest-btn" href="https://forms.gle/mocinVKKF2LHAQbY8" target="_blank" rel="noopener">📝 Öneri Gönder</a>',
            unsafe_allow_html=True,
        )



def apply_template(code: str, name: str = "Şablon") -> None:
    code = (code or "").strip()
    if not code:
        # Eğer kod boşsa, varsayılan kodu kullan
        code = DEFAULT_CODE
    
    parsed_state, error, direction = parse_mermaid(code)
    if error or parsed_state is None:
        toast_error(f"Şablon uygulanamadı: {error or 'Bilinmeyen hata'}")
        return

    st.session_state.flow_state = parsed_state
    st.session_state.direction = direction
    st.session_state.force_layout_reset = True
    normalize_state(st.session_state.flow_state)
    sync_counters_from_state(st.session_state.flow_state)
    sync_code_text(code)
    st.session_state.task_check_fired = False
    st.session_state.selected_node_id = None
    st.session_state.selected_edge_id = None
    st.session_state.auto_connect_anchor = None
    st.session_state.auto_connect_anchor = None

    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action=f"load({name})")
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    toast_success(f"'{name}' yüklendi")
    st.rerun()


def clean_ai_code(code: str) -> str:
    """AI çıktısından yalnızca Mermaid akış bloğunu ayıklar."""
    if not code:
        return code
    cleaned = code.replace("```mermaid", "").replace("```", "").strip()
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    start_idx = None
    for idx, ln in enumerate(lines):
        if FLOW_HEADER_RE.match(ln) or ln.lower().startswith("flowchart") or ln.lower().startswith("graph"):
            start_idx = idx
            break
    if start_idx is None:
        return cleaned
    return "\n".join(lines[start_idx:])


def topic_requires_io(topic: str) -> bool:
    """Konu metninden IO düğümü gereksinimini kaba olarak çıkarır."""
    text = (topic or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return any(hint in text for hint in AI_IO_HINTS)


def get_required_kinds_for_topic(topic: str) -> set[str]:
    required = set(AI_REQUIRED_BASE)
    if topic_requires_io(topic):
        required.add("io")
    return required


def get_ai_min_nodes_for_topic(topic: str) -> int:
    return AI_MIN_NODES_WITH_IO if topic_requires_io(topic) else AI_MIN_NODES_BASE


def action_pool_for_topic(topic: str) -> List[str]:
    """Konuya göre anlamlı işlem etiket havuzu döndürür."""
    text = normalize_label_text(topic).lower()
    if not text:
        return list(DEFAULT_ACTION_POOL)

    if any(k in text for k in ["okul", "okula", "gidiş", "gidis", "servis"]):
        return ["Uyan", "Hazırlan", "Kahvaltı Yap", "Çantayı Al", "Yola Çık", "Okula Var"]
    if any(k in text for k in ["alışveriş", "alisveris", "market", "sipariş", "siparis", "kargo"]):
        return ["Liste Hazırla", "Ürün Seç", "Sepete Ekle", "Kasaya Git", "Ödeme Yap", "Teslim Al"]
    if any(k in text for k in ["giriş", "giris", "login", "oturum"]):
        return ["Kullanıcıyı Doğrula", "Şifre Gir", "Erişim Ver", "Hata Göster"]
    if any(k in text for k in ["kayıt", "kayit", "başvuru", "basvuru"]):
        return ["Bilgi Topla", "Form Doldur", "Belgeleri Yükle", "Onayla", "Başvuruyu Gönder"]
    if any(k in text for k in ["randevu", "rezervasyon", "booking"]):
        return ["Uygunluğu Kontrol Et", "Tarih Seç", "Onayla", "Bildirim Gönder"]
    if any(k in text for k in ["stok", "depo", "envanter"]):
        return ["Stok Kontrol Et", "Sipariş Ver", "Güncelle", "Raporla"]
    if any(k in text for k in ["ödeme", "odeme", "fatura", "tahsil"]):
        return ["Tutar Hesapla", "Ödeme Al", "Makbuz Oluştur", "Kaydı Güncelle"]
    if any(k in text for k in ["robot", "temizlik", "süpürge", "supurge"]):
        return ["Alanı Tara", "Rota Planla", "Temizliği Başlat", "Şarj Ol"]

    return list(DEFAULT_ACTION_POOL)


def parse_ai_flow_or_fallback(code: str, topic: str) -> Tuple[Optional[StreamlitFlowState], str, Optional[str]]:
    """AI çıktısını parse eder; hatada açıklayıcı hata döndürür."""
    code = (code or "").strip()
    code = clean_ai_code(code)
    if not code:
        return None, DEFAULT_DIRECTION, "AI çıktısı boş."

    parsed_state, error, direction = parse_mermaid(code)
    if error or parsed_state is None:
        return None, direction, error or "Geçersiz Mermaid kodu"

    enforce_connected_flow(parsed_state)
    polish_ai_labels(parsed_state, topic)
    repair_ai_kinds(parsed_state)
    simplify_flow_state(parsed_state)
    ensure_decision_edge_labels(parsed_state)

    kinds = {get_node_kind(n) for n in parsed_state.nodes}
    required = get_required_kinds_for_topic(topic)
    min_nodes = get_ai_min_nodes_for_topic(topic)
    if len(parsed_state.nodes) < min_nodes or not required.issubset(kinds):
        toast_warning(
            "AI çıktısı minimum kriterleri karşılamadı; şablon uygulanmadı, mevcut çıktı düzenlendi."
        )

    return parsed_state, direction, None


def extract_free_nodes_from_state(flow_state: StreamlitFlowState) -> List[Dict[str, str]]:
    """State içinden label/kind bilgisi çıkarır."""
    items: List[Dict[str, str]] = []
    for n in sorted(flow_state.nodes, key=lambda x: x.id):
        label = get_node_label(n) or n.id
        kind = get_node_kind(n)
        items.append({"label": label, "kind": kind})
    return items


def apply_ai_flow_template(code: str, topic: str, name: str = "AI Şema") -> None:
    """AI şema çıktısını uygular; hatada kullanıcıya mesaj gösterir."""
    parsed_state, direction, error = parse_ai_flow_or_fallback(code, topic)
    if error or parsed_state is None:
        toast_error(f"AI çıktısı işlenemedi: {error or 'Geçersiz Mermaid kodu'}.")
        return

    # State'i güncelle
    st.session_state.flow_state = parsed_state
    st.session_state.direction = direction
    normalize_state(st.session_state.flow_state)
    sync_counters_from_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.task_check_fired = False
    st.session_state.selected_node_id = None
    st.session_state.selected_edge_id = None
    st.session_state.auto_connect_anchor = None

    # Tarihe ekle
    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action=f"load({name})")
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    
    # Başarı mesajı
    toast_success(f"✨ {name} oluşturuldu: {len(parsed_state.nodes)} düğüm, {len(parsed_state.edges)} bağlantı")
    st.rerun()


def normalize_label_text(label: str) -> str:
    """Etiketten emoji/simgeleri temizle ve sadeleştir."""
    text = (label or "").strip()
    text = re.sub(r"^[^\wÇĞİÖŞÜçğıöşü]+", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def guess_kind_from_label(label: str) -> str:
    """Basit anahtar kelime ile düğüm tipini tahmin et."""
    text = normalize_label_text(label).lower()
    if any(w in text for w in ["başla", "başlangıç", "bitir", "bitti", "son", "start", "begin", "end", "stop", "finish", "entry", "exit"]):
        return "terminal"
    if "?" in label or any(w in text for w in ["mı", "mi", "mu", "mü", "durum", "koşul", "decision", "condition", "check", "if"]):
        return "decision"
    if any(w in text for w in ["giriş", "çıktı", "girdi", "oku", "yaz", "al", "gir", "input", "output", "read", "write", "enter"]):
        return "io"
    if any(w in text for w in ["veritabanı", "kayıt", "db", "tablo", "sakla", "database", "storage", "store"]):
        return "database"
    if any(w in text for w in ["alt süreç", "alt adım", "alt işlem", "subprocess", "sub-process", "subroutine"]):
        return "subprocess"
    if any(w in text for w in ["fonksiyon", "çağır", "çağrısı", "function", "call"]):
        return "function"
    if any(w in text for w in ["not", "açıklama", "bilgi", "ipucu", "note", "comment", "remark"]):
        return "comment"
    if any(w in text for w in ["döngü", "tekrar", "yeniden", "loop"]):
        return "loop"
    if any(w in text for w in ["bağlantı", "konnektör", "devam noktası", "connector", "link", "goto"]):
        return "connector"
    return "process"


def normalize_free_node_items(
    items: Iterable[Union[str, Dict[str, str]]],
    min_count: int = 0,
    max_count: int = FREE_NODES_MAX,
) -> List[Dict[str, str]]:
    """Bağımsız düğüm verilerini normalize eder."""
    normalized: List[Dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            kind = str(item.get("kind", "")).strip()
        else:
            label = str(item).strip()
            kind = "process"

        if not label:
            continue
        if label == label.lower():
            label = turkish_title(label)
        if kind not in NODE_KIND:
            kind = guess_kind_from_label(label)
        if kind not in NODE_KIND:
            kind = "process"
        normalized.append({"label": label, "kind": kind})

    if max_count and len(normalized) > max_count:
        normalized = normalized[:max_count]

    if min_count and len(normalized) < min_count:
        base = normalized[0]["label"] if normalized else "Adım"
        extras = fallback_free_labels(base, count=min_count - len(normalized))
        kind_cycle = list(FREE_KIND_CYCLE)
        for idx, lbl in enumerate(extras):
            kind = kind_cycle[(len(normalized) + idx) % len(kind_cycle)]
            if lbl == lbl.lower():
                lbl = turkish_title(lbl)
            normalized.append({"label": lbl, "kind": kind})

    return normalized


def apply_free_nodes(
    items: List[Union[str, Dict[str, str]]],
    name: str = "Serbest",
    min_count: int = FREE_NODES_MIN,
) -> None:
    """Bağımsız kutuları oluşturur (ok yok)."""
    nodes_input = normalize_free_node_items(items, min_count=min_count, max_count=FREE_NODES_MAX)
    if not nodes_input:
        toast_error("Serbest mod için etiket üretilemedi.")
        return

    # 3xN grid yerleşim
    nodes: List[StreamlitFlowNode] = []
    spacing_x = 260.0
    spacing_y = 160.0
    cols = 3
    for idx, item in enumerate(nodes_input, start=1):
        row = (idx - 1) // cols
        col = (idx - 1) % cols
        pos = (col * spacing_x, row * spacing_y)
        nid = f"n{idx}"
        nodes.append(make_node(nid, item["label"], item["kind"], pos=pos))

    st.session_state.flow_state = make_flow_state(nodes, [])
    st.session_state.direction = "TD"
    normalize_state(st.session_state.flow_state)
    sync_counters_from_state(st.session_state.flow_state)
    sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
    st.session_state.task_check_fired = False
    st.session_state.selected_node_id = None
    st.session_state.selected_edge_id = None
    st.session_state.auto_connect_anchor = None
    st.session_state.auto_connect_anchor = None

    st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action=f"load({name})")
    st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
    toast_success(f"'{name}' yüklendi")
    st.rerun()


# =============================================================================
# Sağ panel: Düğüm / Bağlantı / Kod
# =============================================================================


def render_node_panel(container: st.delta_generator.DeltaGenerator) -> None:
    """Düğüm düzenleme paneli."""
    container.subheader("🧩 Düğüm")
    container.caption("Seçili düğümün metnini ve tipini buradan düzenleyin.")

    nodes = st.session_state.flow_state.nodes
    node_ids = [n.id for n in nodes]

    if not node_ids:
        container.info("Henüz düğüm yok. Üstteki paletten düğüm ekleyin.")
        return

    default_id = st.session_state.selected_node_id or node_ids[0]
    selected_id = container.selectbox(
        "Düğüm Seç",
        node_ids,
        index=node_ids.index(default_id) if default_id in node_ids else 0,
        key="node_select",
    )
    node = find_node(selected_id)
    if node is None:
        container.warning("Düğüm bulunamadı")
        return

    label = get_node_label(node)
    kind = get_node_kind(node)
    width = parse_style_width(getattr(node, "style", {}), 160)

    new_label = container.text_input("Düğüm Metni", value=label, help="Düğümde görünecek metin.")
    kind_options = list(NODE_KIND_ORDER)
    default_kind = kind if kind in NODE_KIND else "process"
    new_kind = container.selectbox(
        "Düğüm Tipi",
        kind_options,
        index=kind_options.index(default_kind) if default_kind in kind_options else 0,
        format_func=lambda k: node_kind_label(k),
        help="Düğümün türünü seçin.",
    )
    new_width = container.slider("Düğüm Boyutu", 100, 320, value=width, step=10, help="Düğüm genişliği.")

    spec = NODE_KIND.get(new_kind, NODE_KIND["process"])
    data = getattr(node, "data", None) or {}
    current_colors = normalize_color_overrides(data.get("colors") if isinstance(data, dict) else None)
    if st.session_state.get("global_node_colors_enabled"):
        container.caption(
            "Global renkler aktif. Buradaki özel renkler yalnızca global kapatıldığında görünür."
        )
    use_custom_colors = container.checkbox(
        "Özel Renk Kullan",
        value=bool(current_colors),
        key=f"node_custom_colors_{selected_id}",
        help="Açıkken arka plan, kenarlık ve yazı rengini özelleştirebilirsiniz.",
    )
    colors_payload: Optional[Dict[str, str]]
    if use_custom_colors:
        new_bg = container.color_picker(
            "Arka Plan",
            value=current_colors.get("bg") or spec["bg"],
            key=f"node_color_bg_{selected_id}",
        )
        new_border = container.color_picker(
            "Kenarlık",
            value=current_colors.get("border") or spec["border"],
            key=f"node_color_border_{selected_id}",
        )
        new_text = container.color_picker(
            "Yazı",
            value=current_colors.get("text") or spec["text"],
            key=f"node_color_text_{selected_id}",
        )
        colors_payload = {"bg": new_bg, "border": new_border, "text": new_text}
    else:
        colors_payload = {}

    col_u, col_d = container.columns(2)
    with col_u:
        if col_u.button("Güncelle", use_container_width=True, key=f"node_update_{selected_id}"):
            src_pos, tgt_pos = default_handle_positions(st.session_state.direction)
            update_node(selected_id, new_label, new_kind, new_width, src_pos, tgt_pos, colors=colors_payload)
            st.rerun()
    with col_d:
        if col_d.button("Sil", use_container_width=True, type="secondary", key=f"node_delete_{selected_id}"):
            delete_node(selected_id)
            st.rerun()


def render_edge_panel(container: st.delta_generator.DeltaGenerator) -> None:
    """Bağlantı düzenleme ve ekleme paneli."""
    container.subheader("🔗 Bağlantı")
    container.caption("Bağlantı etiketini, tipini ve yönünü buradan düzenleyin.")

    edges = st.session_state.flow_state.edges
    edge_ids = [e.id for e in edges]

    # Tek bağlantı etiketi kullanılır (hızlı alan kaldırıldı)

    if not edge_ids:
        container.info("Henüz bağlantı yok. Aşağıdan yeni bağlantı ekleyin.")
    else:
        default_id = st.session_state.selected_edge_id or edge_ids[0]
        selected_id = container.selectbox(
            "Bağlantı Seç",
            edge_ids,
            index=edge_ids.index(default_id) if default_id in edge_ids else 0,
            key="edge_select",
        )
        edge = find_edge(selected_id)
        if edge is None:
            container.warning("Bağlantı bulunamadı")
        else:
            label = get_edge_label(edge)
            etype = get_edge_type(edge)
            variant = get_edge_variant(edge)
            edge_type_labels = list(EDGE_STYLE_ORDER)
            current_type_label = edge_style_label(etype, variant)

            if st.session_state.get("edge_form_id") != selected_id:
                st.session_state.edge_form_id = selected_id
                st.session_state.edge_label_input = label
            new_label = container.text_input(
                "Bağlantı Metni",
                key="edge_label_input",
                help="Bağlantı üzerinde görünecek metin.",
                on_change=apply_edge_label_input,
            )
            if st.session_state.get("allow_edge_style", True):
                new_type_label = container.selectbox(
                    "Bağlantı Tipi",
                    edge_type_labels,
                    index=edge_type_labels.index(current_type_label) if current_type_label in edge_type_labels else 0,
                    help="Çizgi stilini seçin.",
                    key=f"edge_type_{selected_id}",
                )
            else:
                new_type_label = current_type_label

            color_labels = ["Otomatik (türe göre)"] + list(EDGE_COLOR_OPTIONS.keys())
            current_color_label = edge_color_label(get_edge_color(edge))
            color_label = container.selectbox(
                "Bağlantı Rengi",
                color_labels,
                index=color_labels.index(current_color_label) if current_color_label in color_labels else 0,
                key=f"edge_color_{selected_id}",
            )
            color_value = None if color_label == "Otomatik (türe göre)" else EDGE_COLOR_OPTIONS.get(color_label)

            src = edge.source
            tgt = edge.target
            node_ids = [n.id for n in st.session_state.flow_state.nodes]
            new_src = container.selectbox(
                "Kaynak Düğüm",
                node_ids,
                index=node_ids.index(src) if src in node_ids else 0,
                key=f"edge_src_{selected_id}",
            )
            new_tgt = container.selectbox(
                "Hedef Düğüm",
                node_ids,
                index=node_ids.index(tgt) if tgt in node_ids else 0,
                key=f"edge_tgt_{selected_id}",
            )

            col1, col2, col3 = container.columns(3)
            with col1:
                if col1.button("Güncelle", use_container_width=True, key=f"edge_update_{selected_id}"):
                    spec = EDGE_STYLE_OPTIONS.get(new_type_label, {"type": "smoothstep", "variant": "solid"})
                    update_edge(
                        selected_id,
                        new_label.strip(),
                        spec["type"],
                        new_src,
                        new_tgt,
                        spec["variant"],
                        color=color_value,
                    )
                    st.rerun()
            with col2:
                if col2.button("Ters Çevir", use_container_width=True, key=f"edge_reverse_{selected_id}"):
                    reverse_edge(selected_id)
                    st.rerun()
            with col3:
                if col3.button("Sil", use_container_width=True, type="secondary", key=f"edge_delete_{selected_id}"):
                    delete_edge(selected_id)
                    st.rerun()

    container.markdown("---")
    container.markdown("**Bağlantı Ekle**")
    render_edge_builder(container, show_header=False)


def render_edge_builder(container: st.delta_generator.DeltaGenerator, show_header: bool = True) -> None:
    if show_header:
        container.subheader("🔗 Bağlantı Ekle")
        container.caption("Kaynak ve hedef düğüm seçerek yeni bağlantı oluşturun.")

    node_ids = [n.id for n in st.session_state.flow_state.nodes]
    if len(node_ids) < 2:
        container.info("Bağlantı için en az 2 düğüm gerekir.")
        return

    default_src = st.session_state.selected_node_id or st.session_state.last_active_node_id or node_ids[0]
    src = container.selectbox(
        "Kaynak Düğüm",
        node_ids,
        index=node_ids.index(default_src) if default_src in node_ids else 0,
        key="edge_builder_src",
    )

    target_options = [nid for nid in node_ids if nid != src]
    default_tgt = target_options[0]
    tgt = container.selectbox(
        "Hedef Düğüm",
        target_options,
        index=target_options.index(default_tgt) if default_tgt in target_options else 0,
        key="edge_builder_tgt",
    )

    edge_type_labels = list(EDGE_STYLE_ORDER)
    if st.session_state.get("allow_edge_style", True):
        etype_label = container.selectbox(
            "Bağlantı Tipi",
            edge_type_labels,
            index=0,
            key="edge_builder_type",
        )
    else:
        etype_label = "🟢 Yumuşak"
    color_labels = ["Otomatik (türe göre)"] + list(EDGE_COLOR_OPTIONS.keys())
    color_label = container.selectbox("Bağlantı Rengi", color_labels, index=0, key="edge_builder_color")
    color_value = None if color_label == "Otomatik (türe göre)" else EDGE_COLOR_OPTIONS.get(color_label)
    label = container.text_input("Bağlantı Metni (opsiyonel)")

    if container.button("Bağlantı Oluştur", use_container_width=True):
        spec = EDGE_STYLE_OPTIONS.get(etype_label, {"type": "smoothstep", "variant": "solid"})
        add_edge(src, tgt, label.strip(), spec["type"], spec["variant"], color=color_value)
        st.rerun()


def render_control_panel(container: st.delta_generator.DeltaGenerator, compact: bool = False) -> None:
    """Doğrulama, görev ve rubrik panelini render eder."""
    if compact:
        container.markdown("**Kontrol / Hata Bul**")
    else:
        container.subheader("🧪 Kontrol / Hata Bul")

    if st.session_state.get("auto_validate", True):
        items = validate_flow(st.session_state.flow_state)
        if not items:
            container.success("Şimdilik kritik bir sorun görünmüyor.")
        else:
            for item in items:
                if item.level == "error":
                    container.error(item.message)
                elif item.level == "warning":
                    container.warning(item.message)
                else:
                    container.info(item.message)
    else:
        container.info("Otomatik doğrulama kapalı.")

    container.markdown("---")
    if compact:
        container.markdown("**Görev Modu**")
    else:
        container.subheader("🎯 Görev Modu")
    task_names = [""] + list(TASK_LIBRARY.keys())
    prev_task = st.session_state.selected_task
    selected = container.selectbox(
        "Görev Seç",
        task_names,
        index=task_names.index(st.session_state.selected_task) if st.session_state.selected_task in task_names else 0,
    )
    if selected != prev_task:
        st.session_state.task_check_fired = False
    st.session_state.selected_task = selected

    if selected:
        task = TASK_LIBRARY[selected]
        container.markdown(f"**Problem:** {task['problem']}")
        if task.get("min_nodes"):
            container.markdown("**Beklenen Düğüm Türleri:**")
            for kind, count in task["min_nodes"].items():
                container.write(f"- {NODE_KIND.get(kind, {'label': kind})['label']}: {count}+")
        container.markdown("**Minimum Kriterler:**")
        container.write("- Başla ve Bitir düğümleri")
        container.write("- En az bir giriş/çıkış")
        container.write("- Etiketli karar çıkışları (varsa)")

        if container.button("Kontrol Et", use_container_width=True):
            st.session_state.task_check_fired = True

        if st.session_state.task_check_fired:
            task_items = evaluate_task(st.session_state.flow_state, selected)
            if not task_items:
                container.success("Görev kriterleriyle ilgili belirgin bir sorun bulunamadı.")
            else:
                for item in task_items:
                    if item.level == "warning":
                        container.warning(item.message)
                    else:
                        container.info(item.message)

    if st.session_state.get("show_rubric", True):
        container.markdown("---")
        if compact:
            container.markdown("**Rubrik / Puanlama**")
        else:
            container.subheader("📊 Rubrik / Puanlama")
        score, feedback = score_rubric(st.session_state.flow_state)
        container.metric("Toplam Puan", f"{score}/100")
        if feedback:
            for msg in feedback:
                container.info(msg)

    if st.session_state.get("show_pseudocode", True):
        container.markdown("---")
        if compact:
            container.markdown("**Sözde Kod**")
        else:
            container.subheader("🧾 Sözde Kod")
        pseudo = generate_pseudocode(st.session_state.flow_state)
        container.text_area("Sözde Kod", value=pseudo, height=200)


def render_pending_edge_prompt(container: st.delta_generator.DeltaGenerator) -> None:
    edge_id = st.session_state.get("pending_edge_id")
    if not edge_id:
        return
    edge = find_edge(edge_id)
    if edge is None:
        st.session_state.pending_edge_id = None
        return

    with container.expander("Yeni Bağlantı Etiketi", expanded=True):
        current = get_edge_label(edge)
        st.session_state.pending_edge_label = container.text_input(
            "🏷️ Etiket",
            value=st.session_state.pending_edge_label or current,
            key="pending_edge_label_input",
            placeholder="Bağlantı etiketi (opsiyonel)"
        )
        col1, col2 = container.columns(2)
        with col1:
            if col1.button("💾 Kaydet", use_container_width=True, type="primary", key=f"pending_edge_save_{edge_id}"):
                label = st.session_state.pending_edge_label.strip()
                update_edge(
                    edge_id,
                    label,
                    get_edge_type(edge),
                    edge.source,
                    edge.target,
                    get_edge_variant(edge),
                )
                st.session_state.selected_edge_id = edge_id
                st.session_state.edge_form_id = edge_id
                st.session_state.edge_label_input = label
                st.session_state.pending_edge_id = None
                st.session_state.pending_edge_label = ""
                st.rerun()
        with col2:
            if col2.button("⏭️ Atla", use_container_width=True, key=f"pending_edge_skip_{edge_id}"):
                st.session_state.pending_edge_id = None
                st.session_state.pending_edge_label = ""
                st.rerun()


def render_code_panel(container: st.delta_generator.DeltaGenerator) -> None:
    container.subheader("🧩 Mermaid Kodu")
    code = container.text_area(
        "Mermaid",
        value=st.session_state.code_text,
        height=260,
        label_visibility="collapsed",
    )

    if text_hash(code) != st.session_state.last_code_hash:
        parsed_state, error, direction = parse_mermaid(code)
        if error:
            container.error(error)
        else:
            st.session_state.code_text = code
            st.session_state.direction = direction
            st.session_state.flow_state = parsed_state  # type: ignore[assignment]
            normalize_state(st.session_state.flow_state)
            sync_counters_from_state(st.session_state.flow_state)
            st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action="code_edit")
            st.session_state.last_code_hash = text_hash(code)
            st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
            toast_success("Kod tuvale uygulandı")
            st.rerun()

    container.download_button(
        "Kodu İndir (.mmd)",
        st.session_state.code_text,
        file_name=safe_filename(st.session_state.project_title, ".mmd"),
        mime="text/plain",
        use_container_width=True,
    )


# =============================================================================
# Toolbar (tuval altı)
# =============================================================================


def render_toolbar(container: st.delta_generator.DeltaGenerator) -> None:
    """Üst toolbar'ı render eder (Undo/Redo, Reset, Düğüm Paleti).
    
    Args:
        container: Streamlit container (genellikle st.columns()[0])
    
    Toolbar içeriği:
        - Row 1: Geri, İleri, Sıfırla, Seçiliyi Sil
        - Alt satırlar: Düğüm paleti (moda göre filtrelenir)
    
    Side Effects:
        - Butona tıklanınca yeni düğüm eklenir veya undo/redo yapılır
        - Seçili düğüm varsa otomatik bağlantı oluşturulur
    """
    history: HistoryManager = st.session_state.history

    # Kullanıcıya dönen kısa ipuçları (15 sn'de bir)
    try:
        st_autorefresh = getattr(st, "autorefresh", None) or getattr(st, "st_autorefresh", None)
        if st_autorefresh:
            st_autorefresh(interval=15000, key="tip_autorefresh")
    except Exception:
        pass
    tip_idx = int(time.time() // 15) % max(1, len(TIPS))
    tip = TIPS[tip_idx] if TIPS else "İpucu bulunamadı."
    container.info(f"💡 **Nasıl kullanılır:** {tip}", icon="ℹ️")

    allowed = st.session_state.get("allowed_palette", list(NODE_KIND_ORDER))
    controls = container.columns([1, 1, 1, 1], gap="small")

    def label_with_icon(kind: str, label: str) -> str:
        icon = NODE_KIND.get(kind, {}).get("icon", "")
        return f"{icon} {label}".strip()

    with controls[0]:
        undo_label = "⏪ Geri"
        if st.button(undo_label, disabled=not history.can_undo(), use_container_width=True, help="Geri al (Ctrl+Z)"):
            entry = history.undo()
            if entry:
                st.session_state.flow_state = build_state_from_history(entry)
                st.session_state.direction = extract_direction_from_code(entry.code_text) or st.session_state.direction
                normalize_state(st.session_state.flow_state)
                sync_counters_from_state(st.session_state.flow_state)
                sync_code_text(entry.code_text)
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                toast_success(f"⏪ Geri alındı: {entry.action}")
                st.rerun()

    with controls[1]:
        redo_label = "⏩ İleri"
        if st.button(redo_label, disabled=not history.can_redo(), use_container_width=True, help="İleri al (Ctrl+Y)"):
            entry = history.redo()
            if entry:
                st.session_state.flow_state = build_state_from_history(entry)
                st.session_state.direction = extract_direction_from_code(entry.code_text) or st.session_state.direction
                normalize_state(st.session_state.flow_state)
                sync_counters_from_state(st.session_state.flow_state)
                sync_code_text(entry.code_text)
                st.session_state.last_graph_hash = graph_hash(st.session_state.flow_state)
                toast_success(f"⏩ İleri alındı: {entry.action}")
                st.rerun()
    
    with controls[2]:
        if st.button("🔄 Yeni Şemaya Geç", use_container_width=True, help="Seçimi iptal et, yeni şema başlat"):
            # Seçili düğümü iptal et
            st.session_state.selected_node_id = None
            st.session_state.selected_edge_id = None
            st.session_state.last_active_node_id = None
            st.session_state.force_clear_selection = True
            st.session_state.auto_connect_anchor = None
            # Düzeni sıfırla
            st.session_state.force_layout_reset = True
            toast_success("✨ Seçim iptal edildi! Artık yeni düğümler bağımsız eklenecek.")
            st.rerun()

    with controls[3]:
        if st.button("🗑️ Seçiliyi Sil", use_container_width=True, help="Seçili düğüm/bağlantı"):
            delete_selected()

    def add_from_palette(kind: str, label: Optional[str] = None) -> None:
        # Eğer otomatik bağla açıksa ve bir düğüm seçiliyse, yeni düğümü ona bağla
        # Aksi halde bağımsız düğüm oluştur
        connect_from = None
        if st.session_state.get("auto_connect"):
            selected = st.session_state.get("selected_node_id")
            if selected and find_node(selected) is not None:
                connect_from = selected
        if connect_from and find_node(connect_from) is not None:
            # Seçili düğüm varsa, ona bağla
            add_node(kind, label_override=label, connect_from=connect_from)
        else:
            # Seçili düğüm yoksa, bağımsız oluştur
            add_node(kind, label_override=label, connect_from=None)
            st.session_state.selected_node_id = None
            st.session_state.selected_edge_id = None
        st.rerun()

    palette_items = [
        ("terminal", "Başla", "Algoritma başlangıcı"),
        ("io", "Giriş/Çıkış", "Veri al / yaz"),
        ("process", "İşlem", "Hesaplama / atama"),
        ("decision", "Karar", "Koşul kontrolü"),
        ("document", "Belge", "Tek belge / çıktı"),
        ("multi_document", "Çoklu Belgeler", "Birden fazla belge"),
        ("data_storage", "Veri Deposu", "Kalıcı veri saklama"),
        ("internal_storage", "Dahili Depo", "Bellek içi depolama"),
        ("tape_data", "Bant Veri", "Sıralı erişimli kayıt"),
        ("subprocess", "Alt Süreç", "Fonksiyon / alt adım"),
        ("database", "Veritabanı", "Veri saklama"),
        ("display", "Görüntü", "Ekran/çıktı gösterimi"),
        ("manual_input", "Manuel Giriş", "Klavyeden/elden giriş"),
        ("manual_operation", "Manuel İşlem", "Elle yapılan işlem"),
        ("merge", "Birleştir", "Akışları birleştir"),
        ("connector", "Bağlantı", "Bağlantı noktası"),
        ("comment", "Not", "Açıklama / not"),
        ("loop", "Döngü", "Döngü bloğu"),
        ("function", "Fonksiyon", "Fonksiyon çağrısı"),
        ("terminal", "Bitir", "Algoritma sonu"),
    ]
    palette_items = [item for item in palette_items if item[0] in allowed]

    cols_per_row = 6
    for i in range(0, len(palette_items), cols_per_row):
        chunk = palette_items[i : i + cols_per_row]
        row = container.columns([1] * len(chunk), gap="small")
        for col, (kind, label, help_text) in zip(row, chunk):
            with col:
                if st.button(label_with_icon(kind, label), use_container_width=True, help=help_text):
                    add_from_palette(kind, label if kind == "terminal" and label in ("Başla", "Bitir") else None)


# =============================================================================
# Yardımcı: direction çıkarma
# =============================================================================


def extract_direction_from_code(code: str) -> Optional[str]:
    if not code:
        return None
    for raw in code.splitlines():
        m = FLOW_HEADER_RE.match(raw.strip())
        if m:
            return m.group(1).upper()
    return None


# =============================================================================
# Ana Uygulama
# =============================================================================


def main() -> None:
    inject_css()
    inject_tr_translation_script()
    inject_selection_helper_script()
    inject_keyboard_shortcuts()

    initialize_state()
    apply_view_mode()
    show_recovery_banner()
    render_sidebar()
    st.text_input(
        "js_selected_node_id",
        key="js_selected_node_id",
        label_visibility="collapsed",
        on_change=apply_js_selection,
    )

    show_right_panel = st.session_state.get("user_mode", DEFAULT_MODE) != "Basit"

    if show_right_panel:
        col_canvas, col_right = st.columns([5.0, 1.0], gap="large")
    else:
        col_canvas = st.container()
        col_right = None

    with col_canvas:
        sync_selection_from_js(st.session_state.flow_state)
        render_toolbar(st)

        normalize_state(st.session_state.flow_state)
        prev_hash = graph_hash(st.session_state.flow_state)
        prev_edge_ids = {e.id for e in st.session_state.flow_state.edges}
        
        # Koşullu auto-layout: sadece düğüm sayısı değiştiğinde veya reset flag'i varsa
        if "last_node_count" not in st.session_state:
            st.session_state.last_node_count = 0
        if "force_layout_reset" not in st.session_state:
            st.session_state.force_layout_reset = False
        
        current_node_count = len(st.session_state.flow_state.nodes)
        node_count_changed = current_node_count != st.session_state.last_node_count
        should_auto_layout = node_count_changed or st.session_state.force_layout_reset

        layout_dir = DIRECTION_TO_LAYOUT.get(st.session_state.direction, "down")
        if st.session_state.layout_mode == "Manuel (Elle)":
            layout = ManualLayout()
        elif should_auto_layout and st.session_state.layout_mode == "Otomatik (Ağaç)":
            layout = TreeLayout(direction=layout_dir, node_node_spacing=float(st.session_state.node_spacing))
            st.session_state.last_node_count = current_node_count
            st.session_state.force_layout_reset = False
        else:
            layout = ManualLayout()  # Düğüm taşınırken layout sıfırlanmasın

        st.session_state.flow_state = streamlit_flow(
            key="flow",
            state=st.session_state.flow_state,
            layout=layout,
            fit_view=True,
            height=860 if show_right_panel else 920,
            allow_new_edges=True,
            animate_new_edges=False,
            show_controls=st.session_state.show_controls,
            show_minimap=st.session_state.show_minimap,
            get_node_on_click=True,
            get_edge_on_click=True,
            enable_pane_menu=st.session_state.enable_context_menus,
            enable_node_menu=st.session_state.enable_context_menus,
            enable_edge_menu=st.session_state.enable_context_menus,
            hide_watermark=True,
        )

        normalize_state(st.session_state.flow_state)
        update_selection_from_state(st.session_state.flow_state)
        normalize_state(st.session_state.flow_state)

        # Yeni eklenen edge varsa etiketi hızlıca sor
        new_edge_ids = {e.id for e in st.session_state.flow_state.edges} - prev_edge_ids
        if new_edge_ids:
            new_edge_id = next(iter(new_edge_ids))
            new_edge = find_edge(new_edge_id)
            if new_edge is not None and not get_edge_label(new_edge).strip():
                st.session_state.pending_edge_id = new_edge_id
                st.session_state.pending_edge_label = ""

        # Değişiklik varsa Mermaid'i güncelle
        new_hash = graph_hash(st.session_state.flow_state)
        if new_hash != prev_hash:
            sync_code_text(generate_mermaid(st.session_state.flow_state, st.session_state.direction))
            st.session_state.last_graph_hash = new_hash
            action = "graph_change"
            if st.session_state.get("auto_connect_fired"):
                action = "auto_connect"
                st.session_state.auto_connect_fired = False
            st.session_state.history.push(st.session_state.code_text, st.session_state.flow_state, action=action)
    if col_right is not None:
        with col_right:
            render_pending_edge_prompt(st)
            tabs = ["Düğüm", "Bağlantı", "Ayarlar"]
            if st.session_state.show_code:
                tabs.append("Kod")
            tabs.append("Kılavuz")
            tab_objs = st.tabs(tabs)

            idx = 0
            render_node_panel(tab_objs[idx])
            idx += 1
            render_edge_panel(tab_objs[idx])
            idx += 1
            render_settings_panel(tab_objs[idx])
            idx += 1
            if st.session_state.show_code:
                render_code_panel(tab_objs[idx])
                idx += 1
            render_help_panel(tab_objs[idx])
    else:
        with st.sidebar:
            render_pending_edge_prompt(st)

    maybe_auto_save()


if __name__ == "__main__":
    main()
