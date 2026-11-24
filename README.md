# Yoğuşma riski prototipi

Adım 1–4 kapsamında ölçüm doğrulaması, çiğ noktası ve DPU hesabı,
çevrimdışı içe aktarma, referans etiketleme ve geçmiş pencere özellikleri hazır.
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

### Risk olayları ve referans etiketleri

```powershell
.\.venv\Scripts\python.exe -X utf8 -m offline.labels
```

`risk_events.csv` özgün zamanlardaki olayları, `reference_labels.csv` DPU'su
pozitif ham ölçüm anlarındaki 5, 10 ve 15 dakikalık etiketleri içerir.
Boş etiketin nedeni ilgili `issue_*` sütununda bulunur. `label_report.json`
ana 120 saniyelik koşulu ve 0/300 saniyelik duyarlılık koşullarını özetler.
T5 başarı değerlendirmesi model ve ayarlar dondurulduktan sonra yapılır.

### Geçmiş pencereleri ve ortak tahmin adımları

```powershell
.\.venv\Scripts\python.exe -m offline.build_samples
```

`data/processed/windows` içinde her bölüm ve pencere için sıkıştırılmış bir
özellik dosyası üretilir. 150 saniyelik UTC adımları Unix başlangıcına
hizalanır. 5, 10 ve 15 dakikalık pencereler iki uç dahil 3, 5 ve 7 adım
içerir. Adımda yalnızca o anda ulaşmış son geçerli ölçüm kullanılır. Veri
kesintisi veya eksik adım pencereyi sıfırlar.

Referans etiketleri ayrı `*_grid_labels.csv.gz` dosyasındadır. Özellik ve
etiket dosyaları `series_id` ve `timestamp` ile eşleştirilir. Ortak yöntem
karşılaştırmasında `all_windows=1` ve ilgili tahmin süresine ait geçerli
etiket aranır. `window_report.json` bölüm bazındaki sayıları içerir.

### Eşik ve doğrusal eğim adayları

```powershell
.\.venv\Scripts\python.exe -m offline.run_baselines
```

Komut T4 ortak adımlarında dört güvenlik payı ve üç doğrusal eğim penceresi
için ayrı karar sütunları üretir. Sonuçlar `data/processed/baselines` altında
saklanır. Başarı ölçümü ve ayar seçimi sonraki adımda yapılır.

### T4 üzerinde parametre araması

```powershell
.\.venv\Scripts\python.exe -m offline.search_parameters --jobs 4
```

Random Forest adayları ilgili pencere ve tahmin süresi için etiketi olan
T2–T3 kayıtlarında eğitilir. Üç yöntem her tahmin süresinde aynı T4
adımlarında puanlanır. Aday sonuçları ve seçilen ayarlarla üretilen T4
kararları `data/processed/parameter_search`, seçilen üç Random Forest
modeli `models` altında oluşur. Ortak canlı tahmin süresi, müdahale süresi
ölçüldükten sonra seçilir.

### Deney veritabanı

```powershell
.\.venv\Scripts\python.exe -m storage.database
.\.venv\Scripts\python.exe -m storage.export_csv 1 data/runtime/export
```

İlk komut `data/runtime/experiments.sqlite3` dosyasını hazırlar. İkinci komut,
örnekteki `1` kimlikli deney kaydedildikten sonra ölçüm, tahmin ve müdahale
CSV'lerini çıkarır. İsteğe bağlı `--start` ve `--stop` saat dilimi bilgili
zamanlardır. Başlangıç dahil, bitiş hariçtir.

### Kayıt oynatma

```powershell
.\.venv\Scripts\python.exe -m runtime.worker --series T4.LoraA --horizon 15 --limit 500
```

Komut T4 kayıtlarını özgün ölçüm sırasıyla hızlandırılmış biçimde işler.
Sonuçlar `data/runtime/replay.sqlite3` içinde `replay` türünde yeni bir deneye
bağlanır. `--horizon` burada yalnızca yürütülecek aday ayarı seçer. Henüz
arayüz gösterimi olmadığından ilk uyarı gösterim zamanı boş kalır.

### Streamlit ekranları

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

İzleme ekranında kayıt adımları elle veya otomatik ilerletilebilir. İlk
gösterim zamanı, uyarı ekrana çıktığında oynatma veritabanına yazılır. Deney
yönetimi ana deney veritabanını kullanır. Geçmiş kayıtlar iki kaynağı ayrı
gösterir. Yöntem karşılaştırması T4 doğrulama sonuçlarını gösterir.

### Canlı seri akışı

Arayüz açıkken ikinci bir PowerShell terminalinde, proje kökünden:

```powershell
.\.venv\Scripts\python.exe -m runtime.live_worker --demo --horizon 15
```

İzleme ekranında **Canlı akış denemesi** seçilir. Benzetim, bir USB kesintisi
ve yeniden bağlantı içerir. Ölçüm zamanı hızlandırılmıştır. Benzetim kayıtları
`data/runtime/live_demo.sqlite3` dosyasında tutulur.

Kart bağlandığında açık bir deney kimliğiyle USB alıcısı çalıştırılır:

```powershell
.\.venv\Scripts\python.exe -m runtime.live_worker --port COM3 --experiment-id 1 --horizon 15
```

`COM3`, `1` ve `15` örnek değerlerdir. İzleme ekranında **Canlı USB** seçilir.
Tek bir alıcı süreci çalıştırılır. Deney kapatıldığında alıcı kaydı durdurur.
Model ve tahmin süresi bu aşamada ön deneme içindir. Seri mesaj alanları
`firmware/USB_Protokolu.txt` dosyasında tanımlıdır.

### Müdahale süresi ve ayarları sabitleme

En az 30 dakikalık gerçek USB veri akışı doğrulandıktan sonra kullanıcıya
gösterilen uyarıdan kapak kontrolüne kadar geçen süre beş kez ölçülür.
Ölçüm dosyasının başlığı `trial,seconds` olur. İlk sütun 1–5 numaralı
tekrarları, ikinci sütun ölçülen saniyeyi içerir. Ondalık ayırıcı noktadır.

```powershell
.\.venv\Scripts\python.exe -m offline.select_horizon
.\.venv\Scripts\python.exe -m offline.select_horizon --interventions data/runtime/intervention_times.csv
.\.venv\Scripts\python.exe -m offline.freeze_configuration --interventions data/runtime/intervention_times.csv
```

İlk komut ortak T4 olay sayısını gösterir. İkinci komut aday sonuçlarını
gösterir, üçüncü komut üç tahmin süresinin model ve ayarlarını
`data/runtime/frozen` klasöründe sabitler. Ana deneyin USB alıcısında
`--horizon` yerine `--frozen` kullanılır. Alıcı sabitlenmiş araştırma
yapılandırmasını ve model dosyasının bütünlüğünü doğrular.

### Bağımsız T5 değerlendirmesi

Gerçek müdahale süreleri kaydedilip model ve ayarlar sabitlendikten sonra:

```powershell
.\.venv\Scripts\python.exe -m offline.evaluate_test
```

Komut üç tahmin süresinin bağımsız sonuçlarını `data/processed/t5_evaluation`
altına yazar. Kayıt ve olay ölçütleri, yanlış alarm dönemleri, 0/120/300
saniyelik referans sayımları ve seçilen sürenin 24/48 saatlik eşleşmiş
bootstrap analizleri raporda yer alır. Arayüzde T5 sekmesi yalnızca rapor
mevcut sabitlenmiş ayarlara aitse kullanılabilir.

### Deney kutusu değerlendirmesi

Ana deneyler sabitlenmiş ayarlarla yürütülüp kapatıldıktan sonra:

```powershell
.\.venv\Scripts\python.exe -m offline.evaluate_experiments
```

Deney yönetiminde gerçek kapak açma, kapama ve ürün ekleme anları
kaydedilir. Müdahalesiz kontrolde **Kontrol başlangıcı** işaretlenir.
Komut ölçüm sürelerini ve ortak adımları kontrol eder. Erken uyarı
süresinde tahmin zamanı yerine ekranın ilk gösterim zamanını kullanır.
Sonuçlar `data/processed/experiment_evaluation/experiment_report.json`
dosyasındadır ve T5 raporundan ayrıdır. Örnekleme uygunluğu, düzenek
yerleşimi ve fiziksel başlangıç koşulları deney notlarıyla doğrulanır.

Araştırma ayarları `config/research.json` içinde tutulur. Ortak tahmin süresi
ve asgari müdahale süresi henüz seçilmediği için null bırakılmıştır.
