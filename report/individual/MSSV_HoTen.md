# Báo cáo cá nhân — Day 6

- **Họ và tên:** Lê Phạm Thành Đạt — **MSSV:** `2A202604027` — **Lớp:** `L3B`

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - **Chủ đề:** Quản trị rủi ro AI, tính giải thích (Explainable AI), nhận diện/giảm thiểu thiên kiến (AI Bias) và thực hành phát triển phần mềm an toàn cho Generative AI / Dual-Use Foundation Models.
  - **Nguồn và quyền sử dụng:** 3 tài liệu kỹ thuật công bố công khai thuộc phạm vi công cộng của Chính phủ Hoa Kỳ (`U.S. Government Work (17 U.S.C. § 105) — Public Domain`), tải ngày `2026-11-14` (`data/manifest.json`):
    1. `nist-ir-8312` (*Four Principles of Explainable Artificial Intelligence*, `NISTIR 8312 (September 2021)`, [NIST.IR.8312.pdf](file:///g:/Project/VinUni/Day06/starter/data/NIST.IR.8312.pdf), `year=2021`, `category="explainability"`): 43 trang vật lý, **22 trang nội dung hợp lệ**.
    2. `nist-sp-1270` (*Towards a Standard for Identifying and Managing Bias in Artificial Intelligence*, [NIST.SP.1270.pdf](file:///g:/Project/VinUni/Day06/starter/data/NIST.SP.1270.pdf), `year=2022`, `category="bias_management"`): 86 trang vật lý, **48 trang nội dung hợp lệ**.
    3. `nist-sp-800-218a` (*Secure Software Development Practices for Generative AI and Dual-Use Foundation Models*, [NIST.SP.800-218A.pdf](file:///g:/Project/VinUni/Day06/starter/data/NIST.SP.800-218A.pdf), `year=2024`, `category="genai_security"`): 30 trang vật lý, **19 trang nội dung hợp lệ**.
  - **Tổng số trang & quy tắc tính trang:** Tổng **159 trang vật lý** cho **89 trang nội dung hợp lệ** (vượt ngưỡng `≥30` trang) với **255.447 ký tự chuẩn hóa** (`0` trang rỗng, `0` lỗi đọc trang trong [ingestion_log.json](file:///g:/Project/VinUni/Day06/results/ingestion_log.json)). Quy tắc tính trang áp dụng chỉ số trang vật lý 1-based của `pypdf` (`6.21.4`) và loại bỏ các trang bìa/tiêu đề, trang notice/disclaimer, tóm tắt đầu sách/cảm ơn/mục lục, trang chỉ có hình vẽ (`<300` ký tự văn xuôi, như trang 14 của `NIST.IR.8312.pdf` chỉ có 252 ký tự), glossary và tài liệu tham khảo.

- **Chuẩn hóa, lỗi và giới hạn:**
  - Hàm `normalize_text` trong [ingestion.py](file:///g:/Project/VinUni/Day06/starter/src/ingestion.py#L37-L61) thực hiện chuẩn hóa Unicode `NFKC`, gom khoảng trắng ngang `[ \t]+` và tái dựng ranh giới đoạn `\n\n` từ độ dài dòng `p75` (`wrap_threshold = max(58, int(p75_len * 0.86))`) kết hợp bộ nhận diện tiêu đề đánh số/mục con (`_HEADING_OR_ITEM_RE`, `_is_short_heading`).
  - **Lỗi & giới hạn quan sát được:** Một số từ ngắt dòng có dấu gạch nối trong PDF (`explana- tion`, `mathemat- ical`) vẫn giữ nguyên để đồng bộ chuỗi trích dẫn; các câu vắt qua ranh giới trang vật lý không được nối liên trang nên một số chunk đầu trang mở đầu giữa câu (`coh_02`, `coh_04`, `coh_06`); running header đầu trang trên `NIST.SP.800-218A.pdf` có thể tách thành chunk 116 ký tự đứng riêng (`coh_08`); và bộ trích xuất `section` bằng regex đôi lúc bắt nhầm tên cột bảng SSDF trên tài liệu dạng bảng.

- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - **Embedding:** Google Gemini API model `gemini-embedding-001` qua SDK `google-genai==3.3.0`, **768 chiều**, dùng `task_type="RETRIEVAL_DOCUMENT"` khi nạp chunk và `"RETRIEVAL_QUERY"` khi truy vấn, chuẩn hóa L2 (`_l2_normalize`), pacing `batch_size=30`, `max_rpm=90`, disk cache SHA-256 tại `starter/results/.embedding_cache.json` ([embeddings.py](file:///g:/Project/VinUni/Day06/starter/src/embeddings.py)).
  - **Vector store & Metric:** PostgreSQL `16.16 (Debian 16.16-1.pgdg12+1)` + `pgvector 0.8.7` chạy trong Docker container (`day6_student_starter-postgres-1`, port `127.0.0.1:55433`), sử dụng phép đo chính xác **Cosine Distance (`<=>`)** không dùng ANN index (exact search trên 307–605 vectors). Bảng `rag_chunks` có khóa chính `(strategy, chunk_id)` bảo đảm upsert idempotent (`605 -> 605` khi nạp lại Strategy A) và tự xóa chunk lỗi thời theo `(strategy, document_id)` (`obsolete_cleanup_probe`: `2 -> 1`, `deleted_obsolete=1`).
  - **Lệnh chạy (từ `starter/`):** `.\.venv\Scripts\python.exe -m src.run` ([run.py](file:///g:/Project/VinUni/Day06/starter/src/run.py)).
  - **Chi phí:** **\$0** trên Gemini API Free Tier (giới hạn 100 RPM; quá trình chạy chính gửi **30** API calls nhúng **862** chuỗi / **513.110** ký tự mất **50,42 giây** API thuần và **1 lần** tự động chờ `rate_limit_waits` theo RPM/429, cộng **74** chuỗi từ cache ban đầu tạo tổng 936 chuỗi; Strategy C tái sử dụng 307 cache hits từ Strategy B).

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - **Metadata lưu kèm mỗi chunk:** Trường bắt buộc (`source`, `page`), định danh/thống kê chunk (`document_id`, `chunk_index`, `chunk_char_len`) và trường lọc/ngữ cảnh (`year`, `category`, `section`).
  - **Nguồn giá trị:** `document_id`, `source`, `year` và `category` lấy từ `data/manifest.json`; `page` từ số trang vật lý `pypdf` 1-based; `section` trích heuristic từ trang (`_detect_section`); `chunk_index` và `chunk_char_len` tính lúc tạo chunk.
  - **Lý do chọn `year` và `category`:** Phân tách trực tiếp 3 công bố NIST theo năm (`2021`, `2022`, `2024`) và chủ đề chuyên môn (`explainability`, `bias_management`, `genai_security`), có index `(strategy, year, category)` trong Postgres để lọc `WHERE` tức thời và loại trừ nhầm lẫn phạm vi tài liệu.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **Strategy A (Baseline):** `fixed_size(size=500, overlap=50)`, không áp dụng SQL filter → **605 chunks** (min `55`, p50 `500`, mean `464.6`, max `500`, tổng `281.097` ký tự).
  - **Strategy B:** `by_paragraph(max_size=1200)`, overlap `0`, không áp dụng SQL filter → **307 chunks** (min `28`, p50 `928`, mean `833.2`, p95 `1180`, max `1200`, tổng `255.796` ký tự).
  - **Strategy C:** `by_paragraph(max_size=1200)`, overlap `0` (**giống hệt Strategy B** về chunking, embeddings và dữ liệu lưu trữ — **307 chunks**). **Khác biệt duy nhất giữa B và C** là bật `use_filter=True` để thêm mệnh đề SQL `WHERE` theo `year`/`category` khi `question["filter"]` khác `None`.

- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - Bộ benchmark gồm **24 câu hỏi** (`q01`–`q24`) trong [questions.json](file:///g:/Project/VinUni/Day06/benchmark/questions.json), chia thành **18 `dev`** (`6 direct`, `4 paraphrase`, `3 conditional_or_exception`, `5 metadata_filter`: `q05, q13, q14, q21, q22`) và **6 `test`** (`2 direct`, `2 conditional_or_exception`, `2 metadata_filter`: `q08, q24`); tổng cộng **7 câu metadata filter**.
  - **Kiểm chứng evidence:** Từng `gold_page` được đối chiếu thuộc `valid_page_numbers` trong `data/manifest.json` và từng `evidence_quote` được kiểm chứng tự động bằng script (trước khi chạy pipeline) là chuỗi con khớp chính xác sau chuẩn hóa khoảng trắng/NFKC trên đúng trang vàng của PDF (**24/24** hợp lệ).

- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  1. Đạt **Evidence Hit@3** và **Hit@1** cao hơn trên tập `dev` (tài liệu ưu tiên giữ trọn lập luận không bị đứt đoạn như baseline cố định).
  2. Giữ **Chunk Coherence** trung bình đạt ≥ `1.3 / 2`.
  3. **Bắt buộc tuân thủ 100% ràng buộc lọc metadata (`filter compliance`)** cho các câu có điều kiện lọc mà không làm giảm Hit@1/Hit@3; ưu tiên cấu hình thắng trên `dev` và chuyển sang `C` nếu lọc SQL giữ nguyên chất lượng mà loại bỏ được rủi ro rò rỉ chéo tài liệu.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/18 (0.6111) | 13/18 (0.7222) | 605 | 392.4657s ingest (0.8655s query 24 câu) | \$0 (Free Tier) |
| A | test | 4/6 (0.6667) | 5/6 (0.8333) | 605 | cùng lần ingest A | \$0 |
| B | dev | 12/18 (0.6667) | 15/18 (0.8333) | 307 | 242.3729s ingest (0.5620s query 24 câu) | \$0 (Free Tier) |
| B | test | 5/6 (0.8333) | 6/6 (1.0000) | 307 | cùng lần ingest B | \$0 |
| C | dev | 12/18 (0.6667) | 15/18 (0.8333) | 307 | 0.1616s ingest (cache từ B; 0.6173s query) | \$0 (tái dùng cache B) |
| C | test | 5/6 (0.8333) | 6/6 (1.0000) | 307 | cùng lần ingest C | \$0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1.10 / 2 (n=10: 0=0, 1=9, 2=1) | 18/18 trường bắt buộc+lọc (`section` sạch 12/18) | N/A (không lọc SQL; ngẫu nhiên đạt 2/2 test, 7/7 all) | 0/2/4 — TB 1.67 / 2 |
| B | 1.40 / 2 (n=10: 0=1, 1=4, 2=5) | 18/18 trường bắt buộc+lọc (`section` sạch 13/18) | N/A (không lọc SQL; ngẫu nhiên đạt 2/2 test, 7/7 all) | 0/0/6 — TB 2.00 / 2 |
| C | 1.40 / 2 (n=10: 0=1, 1=4, 2=5) | 18/18 trường bắt buộc+lọc (`section` sạch 13/18) | 2/2 test (7/7 cả tập, ép bằng SQL `WHERE`) | 0/0/6 — TB 2.00 / 2 |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Traces & tổng hợp tự động: [metrics_summary.json](file:///g:/Project/VinUni/Day06/results/metrics_summary.json), [traces_all.json](file:///g:/Project/VinUni/Day06/results/traces_all.json), [ingestion_log.json](file:///g:/Project/VinUni/Day06/results/ingestion_log.json).
- Kiểm định Chunk Coherence (10 vị trí chọn trước cố định: `p.8–11` của `nist-ir-8312`, `p.10–12` của `nist-sp-1270`, `p.9–11` của `nist-sp-800-218a` — giữ nguyên thứ tự chunk đầu mỗi trang, không chọn sau khi xem điểm): [coherence_audit_samples.json](file:///g:/Project/VinUni/Day06/results/coherence_audit_samples.json) và [coherence_audit.json](file:///g:/Project/VinUni/Day06/results/coherence_audit.json).
- Kiểm định Metadata & Grounding (toàn bộ 6 câu `test` `q07, q08, q15, q16, q23, q24` × top-3 hits = 18 hits/chiến lược): [metadata_audit.json](file:///g:/Project/VinUni/Day06/results/metadata_audit.json) và [grounding_audit.json](file:///g:/Project/VinUni/Day06/results/grounding_audit.json).
- **Minh bạch gán nhãn:** Theo nguyên tắc `RULES.md`, các nhãn và nhận xét kiểm định thủ công ở 3 file `*_audit.json` được gán thông qua rà soát trực tiếp có AI hỗ trợ trên nguyên văn chunk, metadata và `evidence_quote` thu được (thay mặt học viên), không phải người đánh giá độc lập bên ngoài.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A vs B:** Chuyển từ `fixed_size (500/50)` sang `by_paragraph (1200/0)` giảm gần một nửa số chunk (`605 -> 307`), giảm thời gian ingest từ `392.47s` xuống `242.37s`, đồng thời cải thiện toàn bộ chỉ số chất lượng: `dev Hit@1` `11/18 -> 12/18`, `dev Hit@3` `13/18 -> 15/18`, `test Hit@1` `4/6 -> 5/6`, `test Hit@3` `5/6 -> 6/6`, Coherence `1.10 -> 1.40`, và Grounding `1.67 -> 2.00`. Nguyên nhân cốt lõi là A vẫn tìm trúng đúng trang vàng (`page_hit@3 = 18/18` dev và `6/6` test) nhưng liên tục cắt đôi `evidence_quote` qua ranh giới 500 ký tự (làm hụt `q09, q11, q12, q14, q15, q21` ở `auto Evidence Hit@3`, và cắt mất phần đầu `RV.2.1` ở `A q24` / phần cuối `Kindermans et al.` ở `A q07`).
  - **B vs C:** Trên 7 câu có điều kiện lọc (`q05, q08, q13, q14, q21, q22, q24`), kết quả top-3 và điểm số của **B và C trùng khớp hoàn toàn** (`dev` `12/18` và `15/18`, `test` `5/6` và `6/6`, `7/7 filter compliance`). Điều này xảy ra vì 3 tài liệu NIST thuộc 3 chủ đề khác biệt rõ rệt (`explainability`, `bias_management`, `genai_security`) nên `gemini-embedding-001` đã tự tách cụm không gian ngữ nghĩa ngay cả khi không dùng SQL `WHERE`. Tuy vậy, sự đồng nhất này chỉ mang tính ngẫu nhiên theo đặc thù corpus tách chủ đề; trên corpus nhiều tài liệu cùng chủ đề khác năm (ví dụ bản nháp 2022 vs bản chính thức 2024), chỉ `C` mới bảo đảm không rò rỉ tài liệu ngoài phạm vi lọc.
  - **Ví dụ sai 1 — `q15` (tập `test`, `nist-sp-1270` p. 41, chiến lược A):** Câu hỏi yêu cầu hai điều kiện công bằng toán học bất khả thi và khả năng đạt đồng thời mitigated bias + good performance. Chiến lược A đưa đúng trang 41 lên Rank 1 (`nist-sp-1270:p041:fixed:000`) và Rank 2 (`p041:fixed:001`), nhưng ngưỡng 500 ký tự cắt đôi `evidence_quote` ngay giữa cụm `"While not all mathematical fairness desiderata can be achieved"` → `"mathematical fairness desiderata can be achieved simultaneously..."`, khiến `auto Evidence Hit@3` thất bại (trong khi đọc gộp Rank 1+2 vẫn trả lời đủ cho grounding = 2, và chiến lược B giữ nguyên cả đoạn tại Rank 1 `p041:para:000`).
  - **Ví dụ sai 2 — `q02` (tập `dev`, `nist-ir-8312` p. 10, chiến lược B/C):** Câu hỏi về nguyên tắc `Knowledge Limits` định vị `evidence_quote` tại gạch đầu dòng tóm tắt 1 câu ở trang 10, nhưng B và C lại xếp hạng cao hơn cho toàn bộ **Section 2.4 (`Knowledge Limits`)** ở trang 12 (`p012:para:001` score `0.8060`, `p012:para:002` score `0.7962`) vì Section 2.4 giải thích chuyên sâu hơn câu tóm tắt ở p. 10. Điều này làm `q02` hụt cả `page_hit@3` lẫn `Hit@3` dù chunk truy xuất đúng chủ đề. *(Ngoài ra, ở `q22` tập `dev` trên `nist-sp-800-218a` p. 23, `p023:para:001` ở Rank 2 chứa đúng câu trả lời `"However, it is still beneficial for security purposes..."` nhưng mất câu dẫn đầu của `evidence_quote` ở `para:000` phía trước.)*

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - **Chọn Strategy C (`by_paragraph`, `max_size=1200`, `use_filter=True`):** Thỏa mãn toàn bộ tiêu chí chốt trước khi xem test (thắng rõ rệt A trên `dev`, coherence `1.40/2 > 1.3`, tuân thủ 100% metadata filter qua SQL `WHERE` với khác biệt thời gian truy vấn không đáng kể so với B: `0.6173s` vs `0.5620s` cho 24 truy vấn).
  - **Đánh đổi:** Chunk lớn hơn (`mean=833.2` ký tự) đôi lúc chứa nhiều tiểu mục bảng trên `SP 800-218A` (hoặc tạo outlier 116 ký tự cho running header như `coh_08`), và tăng nhẹ kích thước context đưa vào prompt so với cửa sổ 500 ký tự; đồng thời phụ thuộc độ chính xác của bộ lọc đầu vào từ truy vấn (nếu filter người dùng chỉ định sai năm/chủ đề, kết quả sẽ trống). Phù hợp cho hệ thống RAG tài liệu kỹ thuật/tiêu chuẩn dài có cấu trúc đoạn rõ ràng và yêu cầu phân tách phiên bản/lĩnh vực chặt chẽ.

- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Tập `test` chỉ có **6 câu** nên khoảng tin cậy thô (`1 câu = 16.67%`, chỉ cần khác 1 câu đã nhảy từ `5/6` lên `6/6`); đồng thời 3 tài liệu khác hẳn lĩnh vực nên chưa phơi bày rõ lợi thế loại nhiễu của SQL filter C so với B.
  - Bảng SSDF nhiều cột trong `NIST.SP.800-218A.pdf` làm heuristic `_detect_section` nhiễu trên **5/18 hits** của B/C (`"OWASP:"`, `"Manage 4.1"`, `"Create Source Code..."`) và làm `coh_08` giữ lại running header 116 ký tự.
  - Đo thời gian API bị ảnh hưởng bởi giới hạn **Free Tier RPM (`max_rpm=90` + 1 lần chờ 429)** khiến phần lớn thời gian `392.47s` (A) và `242.37s` (B) là thời gian chờ giới hạn tốc độ chứ không phải độ trễ tính toán thực; đồng thời Strategy A tái dùng `50` chunks đầu đã cache từ lần thử trước pacing (và 24 query đã cache) nên chỉ C mang tính cache toàn phần (`0.1616s`).

- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  1. **Tiền xử lý PDF tốt hơn:** Gỡ running header/footer lặp lại theo vị trí y-coordinate (`pymupdf` / `pdfplumber`), khử dấu gạch nối cuối dòng (`-\s+`), nối câu vắt trang, và parse bảng SSDF của SP 800-218A thành bản ghi có cấu trúc theo mã Practice/Task (`PW.5.1`, `RV.2.1`) để `section` luôn sạch 18/18.
  2. **Mở rộng benchmark & chọn corpus cùng chủ đề đa phiên bản:** Bổ sung thêm các bản NIST cùng lĩnh vực (ví dụ bản draft vs final `NIST AI RMF 1.0` và `NIST AI 600-1`) với ≥50 câu hỏi (≥15–20 câu `test`, nhiều câu trùng từ khóa khác năm) để đo rõ độ chênh giữa B và C và thử nghiệm kết hợp **Hybrid BM25 + Vector + Parent-Child chunking**.
