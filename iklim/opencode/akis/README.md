# PyLocalFlow (Student Edition)

## Proje Amacı

PyLocalFlow, internet bağlantısı veya harici API gerektirmeden, öğrencilerin **sözdizimsel mantık** (Syntax Logic) kullanarak süreç akışları, sınıf diyagramları ve zihin haritaları oluşturmasını sağlayan bir eğitim aracıdır. Amaç sadece çizim yapmak değil, öğrenciye **algoritmik düşünce yapısını kazandırmak**tır.

## Özellikler

- **Offline çalışma:** Tüm işlemler yerel ortamda gerçekleşir.
- **Canlı önizleme:** Kod yazdıkça diyagramı görebilirsiniz.
- **Eğitim odaklı hata mesajları:** Teknik hata yerine anlaşılır ipuçları.
- **Yüksek kaliteli çıktı:** PNG, SVG ve MMD formatları.
- **Başlangıç şablonları:** Boş sayfa, basit akış, Gantt şeması, sınıf diyagramı.

## Kurulum

1. Depoyu klonla veya indir:
   ```bash
   cd path/to/akis
   ```

2. Gereksinimleri yükle:
   ```bash
   pip install -r requirements.txt
   ```

## Çalıştırma

```bash
streamlit run app.py
```

Tarayıcı otomatik olarak `http://localhost:8501` adresine açılacaktır.

## Kullanım

1. Sol panelden bir şablon seç (veya boş sayfayla başla).
2. Mermaid sözdizimini kullanarak diyagramını yaz.
3. "Render" butonuna bas veya kod yazıldıktan sonra bekle.
4. Sağ panelde diyagramını gör.
5. PNG, SVG veya kaynak kodunu indir.

## Teknoloji Stack

- **Python 3.9+**
- **Streamlit:** Web arayüzü
- **Streamlit-Mermaid:** Diyagram render
- **Pillow:** Görüntü işleme

## Eğitim Hedefi

Bu araç, öğrencilere:
- Algoritmaları görsel olarak tasarlamayı
- Kontrol akışını anlamayı
- Yapılandırılmış düşünmeyi
- Sözdizimi ve mantığı öğretmektedir.

---

**Sürüm:** Student Edition v1.0  
**Durum:** Development
