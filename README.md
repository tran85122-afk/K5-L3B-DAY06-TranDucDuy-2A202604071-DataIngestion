# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## 4. Hồ sơ bài nộp và cách chạy lại (2A202604071 — Trần Đức Duy)

| Thành phần | Vị trí |
|---|---|
| Thông tin học viên | [STUDENT.md](STUDENT.md): Trần Đức Duy, MSSV 2A202604071, lớp L3B |
| Corpus và manifest | [data/manifest.json](data/manifest.json): 1 PDF, *World Development Report 2021: Data for Better Lives* (World Bank, CC BY 3.0 IGO). 349 trang vật lý, 201 trang nội dung trích được text, 867.561 ký tự sau chuẩn hóa. Quy tắc tính trang ghi trong manifest. |
| Benchmark | [benchmark/questions.json](benchmark/questions.json): 20 câu, 15 dev / 5 test, 5 câu có filter `chapter`. Cách xây bộ câu hỏi và quy tắc chọn chiến lược nằm trong báo cáo cá nhân. |
| Code pipeline | [starter/src/](starter/src/): `ingestion.py`, `chunking.py`, `embeddings.py` (Gemini `gemini-embedding-001`, 768 chiều), `store.py` (PostgreSQL 16 + pgvector 0.8.7), `evaluation.py`, `run.py` |
| Nhật ký thí nghiệm | [artifacts/experiment_log.csv](artifacts/experiment_log.csv) |
| Kết quả | [starter/results/](starter/results/): `traces.jsonl` (top-3 của 20 câu × 3 cấu hình), `summary.json`, `config.json`, `chunk_stats.json`, `ingest_log.json`, `corpus_pages.csv`, 3 file nhãn chấm tay `audit_*.csv`, log các lần chạy `ingest_run*.txt`, ghi chú quota [INGEST_NOTES.md](starter/results/INGEST_NOTES.md) |
| Báo cáo cá nhân | [report/individual/2A202604071_TranDucDuy.md](report/individual/2A202604071_TranDucDuy.md) |

### Lệnh chạy lại (Windows PowerShell, Python 3.11–3.13, Docker Desktop)

File PDF nặng 50,8 MB nên không có trong repo. Cần tải lại từ World Bank vào `starter/data/` và kiểm tra mã SHA-256 khớp với manifest.

```powershell
cd starter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # rồi điền GEMINI_API_KEY vào .env

Invoke-WebRequest "https://openknowledge.worldbank.org/server/api/core/bitstreams/792e0053-50af-5af0-89f1-ce130a90dd2c/content" -OutFile data\wdr2021.pdf
(Get-FileHash data\wdr2021.pdf -Algorithm SHA256).Hash   # phải là EA4237FC...74A9AC như trong manifest

docker compose -p day6_student_starter up -d --wait
.\.venv\Scripts\python.exe scripts\check_setup.py
.\.venv\Scripts\python.exe -m src.run
```

`src.run` đọc PDF, chia chunk cho hai index A và B, embed rồi lưu vào pgvector, sau đó chạy 20 câu hỏi cho cả ba cấu hình A, B, C. Kết quả được ghi vào `starter/results/`.

Lưu ý:
- Không commit `.env`, `.venv/` hoặc file PDF; các mục này đã có trong `.gitignore`.
- Gói miễn phí của Gemini giới hạn 100 embedding/phút và 1.000 embedding/ngày cho mỗi project. Ingest đầy đủ cần khoảng 3.500 embedding (A có 2.001 chunk, B có 1.495). Nếu hết quota giữa chừng, chạy lại lệnh `src.run` sau khi quota reset: chunk đã lưu sẽ được bỏ qua, không bị embed lại hay trùng lặp.
- Muốn chạy không cần API key thì đặt `EMBEDDING_PROVIDER=local` và cài thêm `sentence-transformers`. Khi đó model khác nên kết quả cũng sẽ khác số liệu trong báo cáo.

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
