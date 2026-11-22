# Yoğuşma riski prototipi

Adım 1 ve 2 tamamlandı. Ortak ölçüm doğrulaması, Magnus çiğ noktası ve DPU
hesabı ile ticari depo kayıtlarını ayıran çevrimdışı içe aktarıcı hazır.
Arayüz elle girilen ölçümler için kontrol ekranıdır.
Henüz sensör bağlantısı, olay etiketleme, model eğitimi veya erken tahmin yoktur.

## Çalıştırma

PowerShell'de proje klasörüne geç:

```powershell
Set-Location 'E:\Tübitak\yogusma'
.\.venv\Scripts\python.exe -X utf8 -m core
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Arayüz: http://127.0.0.1:8501. Durdurmak için terminalde Ctrl+C.
Alternatif başlatıcı: `start.ps1`.

## Doğrulama

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

20 °C ortam, %50 nem, 8 °C yüzey için beklenen çiğ noktası yaklaşık
9,261107 °C ve DPU yaklaşık -1,261107 °C'dir. Negatif DPU anlık koşulu
gösterir; tek başına 120 saniyelik risk olayını doğrulamaz.

Ölçümler saat dilimi bilgili zaman taşır ve UTC'ye çevrilir. Nem 0 < RH <= 100
aralığında olmalıdır. Eksik, sonlu olmayan veya sayısal olmayan alanlar
reddedilir. Hesaplar tam hassasiyetle yapılır; yalnızca ekranda yuvarlanır.

## Ortam

Bu bilgisayarda bağımsız Python kurulumu bulunamadığından `.venv`, Codex'in
paketli Python 3.12 çalışma ortamından oluşturuldu. Codex çalışma ortamı
kaldırılırsa veya yolu değişirse bağımsız Python ile sanal ortamı yeniden
oluşturup `requirements-lock.txt` dosyasından paketleri kurmak gerekir.

`requirements.txt` doğrudan bağımlılıkları, `requirements-lock.txt` bu kurulumun
tam sürümlerini içerir. Python'un `sqlite3` ve `unittest` modülleri ayrıca
kurulum gerektirmez.

## Ticari depo verisini hazırlama

Kaynak, [Mendeley Data, sürüm 2](https://doi.org/10.17632/h4sghvyjyt.2).
`TTH_ColdRoom_June19.zip` dosyasını `data/raw` altında değiştirmeden sakla.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m offline.import_data
```

Komut `data/processed` altında `train.csv`, `validation.csv`, `test.csv`
ve seri bazında sayaçları içeren `import_report.json` dosyasını üretir.
CSV'ler seri içinde zaman sıralıdır. Kaynaktaki `seconds1970` alanı UTC'ye
çevrilir. Geçersiz ölçümlerin zamanları `valid=0` ile korunur. Çelişen
yinelenen ölçümler hesaplamaya alınmaz. Dönem ve UTC bölüm sınırı uyuşmayan
satırlar raporlanır.

Sonraki adım, özgün zaman damgaları üzerinde risk olaylarını ve referans
etiketlerini üretmek. T5 başarı değerlendirmesi model ve ayarlar
dondurulana kadar yapılmamalıdır.

Araştırma ayarları `config/research.json` içinde tutulur. Ortak tahmin süresi
ve asgari müdahale süresi henüz seçilmediği için null bırakılmıştır.
