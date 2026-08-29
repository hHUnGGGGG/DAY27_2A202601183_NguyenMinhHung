# AI Agent Engineering Decision Log

Tài liệu ghi nhận các quyết định thiết kế kỹ thuật, giả thuyết và bằng chứng kiểm thử trong quá trình xây dựng hệ thống Data & AI Reliability.

---

## Decision 1: Explicit Type Validation Without Silent Coercion in Data Contracts

- **Hypothesis:** Việc sử dụng `pd.to_numeric(..., errors='coerce')` đơn thuần có thể âm thầm chuyển đổi các giá trị string lỗi (vd: `"N/A"`, `"NaN"`, `"invalid"`) thành `NaN`, làm ẩn đi lỗi Type Drift ở tầng Ingestion nếu không kiểm tra kiểu dữ liệu gốc một cách chặt chẽ.
- **Prompt / Request to Agent:** "Nâng cấp `src/contract_validator.py` để kiểm tra kiểu dữ liệu (`integer`, `number`, `string`, `datetime`, `boolean`) trực tiếp từ dữ liệu gốc, phát hiện type drift và hỗ trợ contract freshness + severity routing."
- **Agent Proposal:** Xây dựng hàm `_validate_type` riêng biệt. Kiểm tra kiểu `integer` không chấp nhận boolean, float có phần thập phân hoặc chuỗi chứa ký tự chữ. Kiểm tra `datetime` và `string` với độ dài `min_length`/`max_length`.
- **Evidence / Test:** Chạy test `test_type_drift_is_detected` với giá trị `"not_a_number"` trong cột amount -> Validator bắt chính xác lỗi `check='type'` và `check='range'` với severity `critical`.
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Đảm bảo data producer không thể gửi sai kiểu dữ liệu qua Data Contract mà không bị chặn ngay tại ingestion boundary.

---

## Decision 2: Zero-MAD Edge Case Handling in Robust Statistical Anomaly Detection

- **Hypothesis:** Phương pháp Median Absolute Deviation (MAD) rất mạnh trước outliers, nhưng khi phần lớn dữ liệu lịch sử có giá trị giống nhau (vd: hệ thống ổn định tuyệt đối), `mad = 0` sẽ gây ra lỗi chia cho 0 hoặc bỏ sót anomaly.
- **Prompt / Request to Agent:** "Hoàn thiện `mad_detector` trong `observability/anomaly.py` để xử lý triệt để trường hợp `mad == 0.0`. Khi current == median thì không báo lỗi, nhưng khi current lệch khỏi hằng số thì phải phát hiện anomaly."
- **Agent Proposal:** Khi `mad == 0`: nếu `current == median` trả về `score = 0.0, is_anomaly = False`; nếu `current != median` thực hiện fallback tính độ lệch chuẩn (std) hoặc độ lệch tuyệt đối so với trung bình để tính score và so sánh với threshold.
- **Evidence / Test:** Chạy test `test_mad_zero_variance_handling`:
  - `history = [100, 100, 100, 100, 100]`, `current = 100` -> `is_anomaly = False, score = 0.0`.
  - `current = 150` -> `is_anomaly = True` (bắt được anomaly).
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Loại bỏ hoàn toàn false negative khi metric lịch sử có độ biến thiên bằng 0.

---

## Decision 3: Context-Aware Seasonality in Anomaly Detection (`method="auto"`)

- **Hypothesis:** Dữ liệu E-commerce có tính chu kỳ tuần (seasonality): ngày cuối tuần lượng order giảm tự nhiên (~250 rows so với ~600 rows ngày thường). Nếu dùng baseline toàn cục, ngày cuối tuần sẽ bị báo động giả (false positive).
- **Prompt / Request to Agent:** "Cải tiến `detect_anomaly(..., method='auto', context=...)` để tự động nhận diện và sử dụng `same_segment_history` và `day_of_week` từ context."
- **Agent Proposal:** Trong `auto` mode, ưu tiên đọc `context['same_segment_history']` nếu có đủ ít nhất 3 điểm dữ liệu. Đồng thời kiểm tra `context['known_event']` để nới lỏng threshold trong các đợt flash sale/bảo trì. Tự động chọn MAD khi phân phối lệch và Z-Score khi phân phối chuẩn.
- **Evidence / Test:** Chạy test `test_context_aware_segment_history`: với `current = 250` vào ngày Thứ Bảy, auto detector so sánh với Saturday history và trả về `is_anomaly = False`, loại bỏ false alarm.
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Giúp hệ thống giám sát thích ứng với chu kỳ kinh doanh thực tế mà không cần hardcode ngưỡng tĩnh.

---

## Decision 4: dbt Transformation Protection Against SCD Dimension Fanout

- **Hypothesis:** Khi customer dimension (`stg_customers`) có nhiều hơn 1 bản ghi active do lỗi SCD Type 2, phép `left join` trong `fct_daily_revenue` sẽ nhân bản số dòng order và làm sai lệch (thổi phồng) tổng doanh thu mà không hề phát sinh lỗi SQL.
- **Prompt / Request to Agent:** "Viết dbt unit test để expose revenue inflation khi có 2 active rows cho cùng 1 customer, và refactor model `fct_daily_revenue.sql` để chống fanout."
- **Agent Proposal:**
  1. Thêm CTE `deduped_customers` sử dụng window function `row_number() over (partition by customer_id order by valid_from desc) where is_active = true` để lấy bản ghi active mới nhất.
  2. Viết dbt native unit test trong `dbt_project/models/marts/unit_tests.yml` mô phỏng kịch bản 2 active rows cho customer `C0001`.
- **Evidence / Test:** Chạy `python -m dbt.cli.main build --project-dir dbt_project --profiles-dir dbt_project` -> Unit test `test_fct_daily_revenue_sum_and_deduplication` PASS (1/1 unit test, 17/17 data tests pass).
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Bảo vệ báo cáo tài chính của CEO khỏi lỗi logic ẩn trong transformation pipeline.

---

## Decision 5: Transitive Column-Level Lineage Traversal (BFS)

- **Hypothesis:** Để đánh giá chính xác Blast Radius khi một thuộc tính (column) bị lỗi ở raw layer, thuật toán lineage phải duyệt đồ thị phụ thuộc bắc cầu (transitive downstream) thay vì chỉ trả về các direct children.
- **Prompt / Request to Agent:** "Cập nhật `get_column_downstream` trong `observability/lineage.py` sử dụng Breadth-First Search (BFS) để trace toàn bộ downstream columns."
- **Agent Proposal:** Triển khai hàng đợi BFS với `collections.deque` và `seen` set để tránh chu trình, trả về danh sách các node downstream theo thứ tự lan truyền.
- **Evidence / Test:** Chạy test `test_transitive_column_lineage`:
  - `raw_orders.amount` ➔ `stg_orders.amount_usd` ➔ `fct_daily_revenue.daily_revenue` ➔ `ceo_revenue_dashboard.revenue`.
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Cho phép on-call engineer xác định tức thì mọi báo cáo, dashboard và ML feature bị ảnh hưởng khi một trường dữ liệu bị lỗi.

---

## Decision 6: Multi-Window Multi-Burn-Rate Alerting Policy (Google SRE Standard)

- **Hypothesis:** Cảnh báo dựa trên một cửa sổ thời gian ngắn duy nhất dễ gây ra "pager fatigue" do các xung lỗi thoáng qua (transient spikes), trong khi cảnh báo cửa sổ dài lại phản ứng quá chậm với sự cố nghiêm trọng.
- **Prompt / Request to Agent:** "Triển khai `evaluate_multiwindow_burn` theo chuẩn Google SRE Workbook: phân biệt sustained fast burn (page) với transient spike (không page)."
- **Agent Proposal:**
  - Sustained Fast Burn (short >= 14.4x VÀ long >= 14.4x): `page = True`, `severity = 'critical'`.
  - Sustained Medium Burn (short >= 6.0x VÀ long >= 6.0x): `page = True`, `severity = 'critical'`.
  - Transient Spike (short >= 6.0x nhưng long < 6.0x): `page = False`, `severity = 'warning'/'info'`, `action = 'LOG_METRIC_NO_PAGE'`.
  - Healthy: `page = False`, `severity = 'ok'`.
- **Evidence / Test:** Chạy test `test_multiwindow_burn_rate_policies`:
  - Transient spike (short=18.0x, long=1.5x) trả về `page = False`.
  - Sustained fast burn (short=15.0x, long=15.0x) trả về `page = True`.
- **Accept / Reject / Revise:** **Accept**.
- **Why:** Tối ưu hóa hiệu quả trực nhật on-call, giảm thiểu báo động giả mà vẫn bắt kịp thời sự cố tiêu tốn error budget.
