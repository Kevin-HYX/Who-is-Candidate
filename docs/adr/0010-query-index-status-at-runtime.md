# 运行时计算索引状态

MCP 使用指南不硬编码运行时覆盖数字。Agent 在假设搜索 ready 或 full 前，必须读取只读资源 `candidate://index-status`，检查当前 Raw、Preprocessed、Embedding 和 index 覆盖。这样可以防止静态指南与实际数据集或重建后的本地 artifact 漂移，同时让运行时状态与 Query 编写指南保持分离。

运行时状态不作为动态记录持久化，而是根据实际 Raw、Preprocessed、Embedding、Mapping、Result、Error artifact、当前版本和 hash 实时计算。CLI 状态命令、MCP resource、Evaluation Browse、Search readiness 与 Retrieval Trial prerequisites 必须复用同一计算实现，避免任何 adapter 得出不同的 readiness 或覆盖结论。
