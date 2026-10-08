from personal_assistant.knowledge_base import (
    build_vector_store,
    ensure_writable_tempdir,
)


def main() -> None:
    # 环境适配放在入口：库本身不改进程全局状态。
    # 临时目录正常时不打印任何东西（见 knowledge_base.ensure_writable_tempdir）。
    ensure_writable_tempdir()

    # 执行解析、切分、Embedding 和 Chroma 写入。
    summary = build_vector_store()

    # 打印真实构建结果，方便检查。
    print("向量库构建完成：")
    print(f"- 原始文档：{summary['document_count']}")
    print(f"- 文本分块：{summary['chunk_count']}")
    print(f"- 索引目录：{summary['vector_store_path']}")
    print(f"- Embedding：{summary['embedding_model']}")

    # 计划 P2 的通过信号要求打印每份文件的「解析方式 / chunk 数 / 是否机器识别」，
    # 这里补齐；多模态文档另外标出实际使用的模型（provenance）。
    print("- 每份文件：")
    for item in summary.get("documents", []):
        provenance = item.get("provenance") or {}
        extra = ""
        if provenance:
            extra = (
                f"  来源={provenance.get('model_name', '?')}"
                f"/{provenance.get('config_source', '?')}"
            )
            if provenance.get("vision_error"):
                extra += f"  vision_error={provenance['vision_error'][:60]}"
        print(
            f"  · {item['document_id']}  {item['parser_mode_actual']}  "
            f"{item['chunk_count']} chunk  机器识别={item['is_machine_extracted']}{extra}"
        )

    # K7：解析失败的文档不静默丢弃，在这里如实打印（课件 §5.4 版本没有这一段）。
    failures = summary.get("failures") or []
    if failures:
        print(f"- 解析失败：{len(failures)} 份（已记入 index_manifest.json）")
        for item in failures:
            print(f"  · {item['path']} [{item['error_type']}] {item['error_message']}")


if __name__ == "__main__":
    main()
