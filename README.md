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

## 4. Hồ sơ bài nộp & Hướng dẫn chạy tái lập (2A202604027 — Lê Phạm Thành Đạt)

- **Thông tin học viên:** [STUDENT.md](STUDENT.md) — **Họ tên:** Lê Phạm Thành Đạt — **MSSV:** `2A202604027` — **Lớp:** `L3B`
- **Corpus & Manifest:** [data/manifest.json](data/manifest.json) (3 PDF Public Domain NIST tại `starter/data/`: `NIST.IR.8312.pdf`, `NIST.SP.1270.pdf`, `NIST.SP.800-218A.pdf` — 159 trang vật lý / **89 trang nội dung hợp lệ** / 255.447 ký tự chuẩn hóa)
- **Benchmark (24 câu hỏi, 18 dev / 6 test, 7 metadata filter):** [benchmark/questions.json](benchmark/questions.json)
- **Pipeline source (`starter/src/`):** `ingestion.py`, `chunking.py`, `embeddings.py` (`gemini-embedding-001`, 768 chiều), `store.py` (PostgreSQL 16.16 + `pgvector 0.8.7`), `evaluation.py`, `run.py`
- **Nhật ký & Kết quả:** [artifacts/experiment_log.csv](artifacts/experiment_log.csv), thư mục [results/](results/) (đồng bộ cùng `starter/results/`)
- **Báo cáo cá nhân & Tổng hợp trực quan HTML:** [report/individual/2A202604027_LePhamThanhDat.md](report/individual/2A202604027_LePhamThanhDat.md), [index.html](index.html) / [report/day06_lab_report.html](report/day06_lab_report.html)

### Lệnh chạy tái lập (Windows PowerShell, từ `starter/`)

```powershell
cd starter
docker compose -p day6_student_starter up -d --wait
.\.venv\Scripts\python.exe scripts\check_setup.py
.\.venv\Scripts\python.exe -m src.run
```

> Lưu ý: Tạo `starter/.env` từ [starter/.env.example](starter/.env.example) và điền `GEMINI_API_KEY` (không commit `.env`, `.venv/` hoặc `.embedding_cache.json`).
