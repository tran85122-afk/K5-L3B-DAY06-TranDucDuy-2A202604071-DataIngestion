# Báo cáo cá nhân — Day 6

Họ và tên: Trần Đức Duy - MSSV 2A202604071 - Lớp L3B

## Dữ liệu và pipeline

**Chủ đề, nguồn, quyền và cách tính trang.**
- Chủ đề: quản trị dữ liệu cho phát triển.
- Tài liệu: *World Development Report 2021: Data for Better Lives* của World Bank (DOI 10.1596/978-1-4648-1600-0), lấy từ Open Knowledge Repository của World Bank.
- Giấy phép: CC BY 3.0 IGO.
- File PDF nặng 50,8 MB nên không đưa lên git. Đường dẫn tải và mã SHA-256 để kiểm tra nằm trong `data/manifest.json`.

PDF có 349 trang vật lý. Chỉ tính phần thân của Overview và 9 chương, gồm 10 dải trang: 23–37, 43–62, 73–94, 111–130, 141–162, 177–197, 209–228, 247–269, 285–307, 323–341. Phần bị loại: bìa, mục lục, lời nói đầu, trang mở đầu mỗi Part, Notes/References và Spotlight. Ranh giới các dải lấy từ bookmark của file PDF.

Trong 205 trang thuộc các dải:
- 201 trang trích được text, tổng 867.561 ký tự sau chuẩn hóa (`starter/results/corpus_pages.csv`).
- 4 trang bản đồ (29, 77, 79, 142) không đọc được.

Số trang ở mọi nơi (manifest, database, trace, `gold_page`) là số trang vật lý của PDF, đếm từ 1.

**Chuẩn hóa, lỗi và giới hạn.** Đọc PDF bằng pypdf 6.21.4. Bước chuẩn hóa:
- Đưa text về Unicode NFC, gộp khoảng trắng thừa, giữ chỗ xuống dòng giữa các đoạn.
- Nối lại từ bị gạch nối ở cuối dòng.
- Bỏ dòng header lặp ở đầu trang (ví dụ "26 | World Development Report 2021") bằng regex khai báo trong manifest.

Các vấn đề còn tồn tại:
- **Chữ ghép bị tách:** pypdf tách các chữ ghép fi, fl, ffi, ví dụ "identifi cation", "fl ow", "offi cial", "benefi ciaries". Lỗi được phát hiện sau khi index A đã embed xong. Sửa bước chuẩn hóa sẽ làm đổi text của chunk và phải embed lại toàn bộ, vượt quá quota API, nên giữ nguyên và ghi vào phần hạn chế.
- **Trang không đọc được:** 4 trang bản đồ báo lỗi `LimitReachedError` trong pypdf. Chúng được ghi vào `starter/results/ingest_log.json`, cùng với 16 trang rỗng ngoài các dải (bìa, trang trắng) và trang 171 (lỗi, ngoài dải).
- **Nhãn biểu đồ lẫn vào text:** một số nhãn trục biểu đồ bị đọc thành văn bản, ví dụ chunk `wdr2021:p86:p5` và `wdr2021:p186:f7`.

**Nạp lại không trùng.** Mỗi chunk có ID cố định và mã hash nội dung. Khi chạy lại, chunk không đổi được bỏ qua, chunk không còn trong corpus bị xóa. Ở lần chạy benchmark cuối:
- Index A: `embedded_this_run: 0`, `unchanged_skipped: 2001`, `rows_in_store: 2001`.
- Index B: tương tự, với 1495 chunk.

Số liệu nằm trong `starter/results/chunk_stats.json` và `run_benchmark.txt`.

**Embedding, vector store, lệnh chạy và chi phí.**
- *Embedding:* Gemini API, model `gemini-embedding-001`, 768 chiều. Chunk dùng `taskType = RETRIEVAL_DOCUMENT`, câu hỏi dùng `RETRIEVAL_QUERY`.
- *Vector store:* PostgreSQL 16 + pgvector 0.8.7 (image `pgvector/pgvector:0.8.7-pg16`, chạy local ở cổng 55433), kết nối qua psycopg 3.3.8. Khoảng cách cosine (`<=>`), exact search, không dùng ANN index vì mỗi index chỉ có 1.500–2.000 vector. Mỗi câu hỏi lấy top-3.
- *Lệnh chạy:* trong `starter/`, chạy `python -m src.run`. Lệnh không nhận tham số; đường dẫn manifest và benchmark cố định trong code. Lần chạy benchmark cuối: 2026-11-14T05:42:52 UTC (`config.json`).
- *Chi phí:* 0 USD (gói miễn phí). Gói này giới hạn 100 request/phút và 1.000 request/ngày cho mỗi project, mỗi chunk tính là một request. Vì vậy ingest chạy thành 5 lần trong ngày 14/11, dùng key của nhiều project. Chi tiết trong `starter/results/INGEST_NOTES.md`.

**Metadata.** Mỗi chunk lưu `document_id`, `source`, `page` ở cột riêng. Các trường còn lại nằm trong cột JSON: `char_start`, `char_end`, `title`, `year`, `document_type`, `language`, `part`, `chapter`, `chapter_title`.

Trường lọc là `chapter` (overview, 1–9), kèm `part` (overview, I, II, III). Giá trị lấy trực tiếp từ dải trang trong manifest theo mục lục của báo cáo, không suy đoán.

Lý do chọn `chapter`: nhiều chủ đề trong báo cáo lặp lại ở nhiều chương với góc nhìn khác nhau. Ví dụ, bảo vệ dữ liệu xuất hiện ở chương 6 (pháp lý), chương 7 (thương mại, luồng dữ liệu xuyên biên giới) và chương 8 (thể chế). Khi biết câu hỏi thuộc chương nào, lọc theo `chapter` loại được các đoạn đúng chủ đề nhưng sai bối cảnh.

## Cấu hình và benchmark

**Ba cấu hình:**
- **A:** cắt cố định 500 ký tự, chồng lấn 50 ký tự, trong từng trang. 2.001 chunk; ngắn nhất 56, trung bình 478, dài nhất 500 ký tự. Không lọc.
- **B:** gom các đoạn văn liền nhau trong cùng trang thành chunk tối đa 800 ký tự, không chồng lấn; đoạn dài hơn 800 ký tự được tách ở cuối câu. 1.495 chunk; ngắn nhất 29, trung bình 580, trung vị 622 ký tự. Không lọc.
- **C:** dùng lại index của B. Khác biệt duy nhất nằm ở truy vấn: với 5 câu có `filter`, C thêm điều kiện `metadata ->> 'chapter' = <giá trị>` vào SQL trước khi xếp hạng. 15 câu còn lại chạy giống B.

A–B chỉ khác cách chia chunk; B–C chỉ khác việc lọc metadata.

**Bộ câu hỏi.** `benchmark/questions.json` gồm 20 câu tiếng Anh (cùng ngôn ngữ với tài liệu), chia trước khi chạy thành 15 câu dev (q01–q15) và 5 câu test (t16–t20). Ba loại câu:
- `direct`: hỏi một sự kiện có sẵn trong văn bản.
- `paraphrase`: diễn đạt khác với nguồn.
- `condition`: đáp án phụ thuộc một điều kiện hoặc ngoại lệ.

5 câu có filter theo `chapter`:
- Dev: q05 (chương 2), q11 (chương 5), q14 (chương 8).
- Test: t16 (chương 7), t18 (chương 6).

Filter được coi là thông tin có sẵn trước khi hỏi, ví dụ người dùng đang đọc chương đó. Câu test lấy từ các trang không trùng với câu dev.

Mỗi `evidence_quote` được chép nguyên văn từ trang gold. Pipeline kiểm tra từng quote có nằm trên trang đó sau chuẩn hóa không và dừng nếu sai. Kết quả: 20/20 khớp.

**Quy tắc chọn chiến lược (chốt trước khi chạy benchmark):**
1. Chọn chiến lược có dev Evidence Hit@3 cao nhất.
2. Nếu chênh không quá 1 câu, xét dev Hit@1.
3. Nếu vẫn hòa, chọn chiến lược tốn ít tài nguyên hơn (ít chunk, ít lượt embed).

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/15 | 12/15 | 2001 | xem ghi chú | 0 USD |
| A | test | 2/5 | 4/5 | 2001 | | 0 USD |
| B | dev | 12/15 | 14/15 | 1495 | xem ghi chú | 0 USD |
| B | test | 2/5 | 4/5 | 1495 | | 0 USD |
| C | dev | 12/15 | 14/15 | 1495 (dùng index B) | không tốn thêm | 0 USD |
| C | test | 2/5 | 5/5 | 1495 (dùng index B) | không tốn thêm | 0 USD |

*Ghi chú về thời gian:* tốc độ ingest bị giới hạn bởi quota (khoảng 100 chunk/phút), không phải bởi code, nên thời gian chạy không phản ánh chi phí thật của A hay B. Hai số đo được trong log: 301 chunk cuối của A mất 241,7 giây; 895 chunk cuối của B mất 544,5 giây. Số lượt gọi embed là thước đo công bằng hơn: A cần 2.001 lượt, B cần 1.495, ít hơn khoảng 25%.

| Strategy | Coherence TB /2 (n) | Metadata đủ và đúng (n/N) | Tuân thủ filter (n/N) | Grounding 0/1/2 (số câu), TB /2 |
|---|---|---|---|---|
| A | 1,00 (n=10) | 15/15 | dev 2/3, test 1/2 | 0/1/4, TB 1,80 |
| B | 2,00 (n=10) | 15/15 | dev 3/3, test 1/2 | 1/0/4, TB 1,60 |
| C | 2,00 (n=10, chung chunk với B) | 15/15 | dev 3/3, test 2/2 | 0/0/5, TB 2,00 |

**Trace và nhãn chấm tay:**
- `starter/results/traces.jsonl`: 60 lượt truy vấn (20 câu × 3 cấu hình), gồm text, score và metadata của top-3.
- `summary.json`: các chỉ số tự động.
- `audit_coherence.csv`: 10 vị trí, là điểm giữa của 10 trang đầu tiên theo thứ tự trang (23–28 và 30–33; trang 29 bị bỏ vì không đọc được). Chấm chunk chứa vị trí đó ở index A và index B; C dùng chung chunk với B nên cùng điểm.
- `audit_metadata.csv`: 5 câu test × 3 cấu hình × top-3, tổng 45 kết quả, đối chiếu `source`, `page`, `chapter`/`part` với PDF. Cả 45 đều có metadata đúng.
- `audit_grounding.csv`: 5 câu test × 3 cấu hình, thang 0 (không có bằng chứng), 1 (có nhưng thiếu ý hoặc thiếu điều kiện), 2 (đủ để trả lời và truy nguồn).

## Phân tích và kết luận

### So sánh A và B (đổi cách chia chunk)

Chunk chia theo đoạn dễ đọc hơn rõ rệt. Cả 10 mẫu của A đều bị cắt giữa câu hoặc giữa từ, nên được 1 điểm; ví dụ `wdr2021:p26:f5` bắt đầu bằng "ohn Locke..." và kết thúc ở "the infrastr". Cả 10 mẫu của B đều giữ trọn ý.

Truy xuất cũng tốt hơn: dev Hit@3 tăng từ 12/15 lên 14/15, dev Hit@1 từ 11/15 lên 12/15, trong khi số chunk giảm khoảng 25%.

- **Ví dụ lỗi 1 (t19, test, trang 326, chương 9):** chunk top-1 của A là `p326:f3`. Ranh giới 500 ký tự rơi giữa câu, nên phần đầu "To the extent possible, robust data protection is achieved" nằm ở chunk trước; chunk này chỉ còn "by legal and technological solutions before restricting access to data...". Kết quả: A không có chunk nào chứa trọn evidence (Hit@3 = 0), grounding 1. B và C lấy được nguyên đoạn `p326:p2` ở top-1.
- **Ví dụ lỗi 2 (q02, dev, trang 45, chương 1):** A trả về trang 50, 51 và 23, không có trang 45. B và C lấy đúng `p45:p1` ở top-1 (score 0,756). Câu q10 (trang 180) tương tự: A trả về trang 187, 179, 30; B và C trúng `p180:p2` ở top-1.
- **Lỗi chung của cả ba (q03, dev, trang 48):** cả ba đều có trang 48 trong top-3, nhưng không chunk nào chứa trọn câu evidence, nên vẫn tính là trượt theo định nghĩa của đề. Ở B và C, đoạn `p145:p0` (chương 4, cũng nói về độ kịp thời của private intent data) xếp trên trang 48 với điểm rất sát: 0,8125 so với 0,8116.

### So sánh B và C (thêm filter)

Trên dev, B và C cho kết quả như nhau: Hit@1 12/15, Hit@3 14/15, tuân thủ filter 3/3. Khác biệt chỉ xuất hiện ở test.

- **Ví dụ lỗi 3 (t18, test, filter chương 6, trang 212):** câu hỏi là vì sao Convention 108 được cập nhật thành 108+. Không có filter, B lấy về:
  - `p307:p8`: chương 8, chunk chỉ 97 ký tự.
  - `p213:p5`: nói về MLAT và Công ước Budapest.
  - `p265:p0`: chương 7, chỉ nhắc tên "modernized Convention 108", không giải thích.

  Grounding của B bằng 0. C lọc `chapter = 6` nên loại các chunk của chương 7 và 8, đưa `p212:p2` lên hạng 2. Chunk này chứa nguyên câu "Convention 108 was updated to Convention 108+ in response to the entry into force of the GDPR", grounding đạt 2.
- Ở dev, câu q05 (filter chương 2) cho thấy vấn đề tương tự với A: hạng 2 là `p186:f7`, một mảnh nhãn biểu đồ thuộc chương 5.

### Chọn chiến lược

Áp dụng quy tắc đã chốt:
- **Bước 1:** B và C cùng 14/15 trên dev, cao hơn A (12/15).
- **Bước 2:** B và C cùng 12/15 Hit@1.
- **Bước 3:** B và C dùng chung một index nên tài nguyên như nhau.

Quy tắc không phân định được B và C. Đây là thiếu sót của quy tắc: chưa tính trường hợp hai cấu hình dùng chung index.

Chiến lược được chọn là C, vì C giống hệt B khi câu hỏi không có filter, còn khi có filter thì C đảm bảo kết quả nằm đúng phạm vi yêu cầu. Kết quả test đã được xem trước khi viết phần này. Vì vậy kết quả 5/5 của C trên test chỉ là số liệu báo cáo thêm, không phải căn cứ để chọn, và không nên coi là kiểm tra độc lập hoàn toàn.

**Đánh đổi:**
- Chia theo đoạn giảm số chunk và giữ trọn ý, nhưng sinh ra một số chunk rất ngắn ở đầu hoặc cuối trang (ngắn nhất 29 ký tự). Chunk ngắn như `p307:p8` (97 ký tự) có thể đạt điểm cosine cao một cách không đáng tin.
- Lọc cứng theo chương cho kết quả đúng phạm vi nhưng chỉ dùng được khi biết trước chương. Nếu chọn sai chương, câu trả lời đúng bị loại hoàn toàn.

**Phạm vi áp dụng:** tài liệu dài, chia chương rõ ràng (báo cáo, sổ tay, quy chuẩn), kèm giao diện hoặc agent xác định được phạm vi câu hỏi.

### Hạn chế

1. **Lỗi chữ ghép từ pypdf** ("identifi cation", "fl ow"...) làm sai từ khóa và có thể ảnh hưởng embedding. Không sửa được vì phải embed lại toàn bộ.
2. **Bốn trang bản đồ** (29, 77, 79, 142) không đọc được; một số nhãn biểu đồ lẫn vào chunk.
3. **Tập test nhỏ (5 câu):** chênh một câu là chênh 20%. Câu hỏi được soạn từ chính văn bản nên cách hỏi gần với nguồn hơn câu hỏi thực tế. Người chấm tay cũng là người làm bài, nên có thể thiên lệch.
4. **Chunk không vượt qua ranh giới trang:** đoạn văn bị ngắt giữa hai trang vẫn bị cắt.
5. **Thời gian ingest bị quota chi phối:** ingest chia thành 5 lần chạy trong cùng ngày; thời gian đo được chủ yếu là thời gian chờ quota, không phải thời gian xử lý.

### Hướng cải thiện

1. Dùng PyMuPDF hoặc Docling để đọc PDF, xử lý chữ ghép từ đầu, và dùng OCR cho các trang bản đồ.
2. Cho phép chunk nối qua ranh giới trang; đặt độ dài tối thiểu khoảng 150 ký tự để gộp các chunk quá ngắn.
3. Kết hợp vector search với tìm kiếm từ khóa (full-text search của PostgreSQL) cho các câu như q03. Khi không chắc chương, dùng metadata để tăng điểm (boost) thay vì lọc cứng.
4. Mở rộng tập test lên 40–50 câu, thêm câu hỏi cần ghép nhiều trang và câu không có đáp án; nhờ người khác chấm nhãn độc lập.
