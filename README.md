# Similar Cases Retrieval

Repository giữ ba pipeline tạo embedding độc lập:

1. `code/ehr_graph_embedding/`: biểu diễn một visit EHR thành graph, pretrain
   GNN qua ba stage và xuất một embedding cho mỗi visit.
2. `code/image_embedding_pipeline/`: đưa ảnh y khoa qua encoder phù hợp với
   modality và xuất embedding ảnh.
3. `code/text_embedding_pipeline/`: gom toàn bộ clinical note theo visit, đưa
   qua Qwen3-Embedding-8B và xuất embedding văn bản.

`code/image_embedding_pipeline/merge_image_cases_with_ehr.py` nối image
embedding vào đúng `visit_id` để chuẩn bị candidate pool cho retrieval v2.
Retrieval/fusion chính thức chưa được triển khai.

## Đọc trước khi tiếp tục ở chat khác

1. [docs/STATUS.md](docs/STATUS.md): trạng thái và việc chưa chốt.
2. [docs/PIPELINES.md](docs/PIPELINES.md): luồng ba encoder và hai bản retrieval.
3. [docs/DATA.md](docs/DATA.md): data contract, ID và artifact hiện có.
4. [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md): các run đã hoàn tất.

Code server: `/mnt/disk4/similar_cases_retrieval/code/`. Dữ liệu và model
artifact chỉ tồn tại trên Vaipe, không đưa vào Git.
