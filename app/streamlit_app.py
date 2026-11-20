"""Streamlit demo for the shipping bill agent.

Run:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if __name__ == "__main__":
    # Directly double-clicking/running this .py is not a Streamlit server.
    # Start it through start_app.bat or `streamlit run ...` instead.
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx() is None:
            print(
                "请使用项目根目录的 start_app.bat 启动，"
                "或运行：streamlit run app/streamlit_app.py"
            )
            raise SystemExit(0)
    except ImportError:
        pass

import streamlit as st  # noqa: E402

from shipping_agent.ai_config import (  # noqa: E402
    AIConfig,
    clear_saved_config,
    detect_platform_config,
    has_saved_config,
    load_saved_config,
    save_ai_config,
)
from shipping_agent.io.context import ParseError  # noqa: E402
from shipping_agent.io.url_fetcher import split_urls  # noqa: E402
from shipping_agent.ui_service import (  # noqa: E402
    analyze_bytes,
    analyze_url,
    audit_payload,
    classification_payload,
    extraction_payload,
    records_payload,
    summary_rows,
)

st.set_page_config(
    page_title="航运智能账单助手",
    page_icon="🚢",
    layout="wide",
)

DEFAULT_BILLS = str(ROOT / "data" / "fixtures" / "existing_bills.json")
DEFAULT_ENTITY = "IMPORTER BETA (SHANGHAI)"
PROVIDER_OPTIONS = ("deepseek", "openai", "anthropic")


def _provider_defaults(provider: str) -> tuple[str, str]:
    return {
        "deepseek": ("deepseek-chat", "https://api.deepseek.com/v1"),
        "openai": ("gpt-4o-mini", "https://api.openai.com/v1"),
        "anthropic": ("claude-sonnet-5-5", "https://api.anthropic.com"),
    }.get(provider, ("deepseek-chat", "https://api.deepseek.com/v1"))


def _vision_fallback_status() -> tuple[bool, str, str]:
    """Return (configured, model, protocol) for the final image fallback."""
    try:
        from shipping_agent.vision_extractor import VisionConfig

        config = VisionConfig.from_env()
        return config.enabled, config.model, config.protocol
    except Exception:
        return False, "", ""


def _result_payload(analysis) -> dict:
    bundle = analysis.bundle
    return {
        "rows": summary_rows(analysis),
        "classification": classification_payload(analysis),
        "extraction": extraction_payload(analysis),
        "full_json": records_payload(analysis, "full"),
        "strict_json": records_payload(analysis, "strict"),
        "audit_json": audit_payload(analysis),
        "record_count": len(analysis.pipeline.records),
        "parse_status": {
            "ocr_mode": bundle.ocr_mode,
            "media_type": bundle.media_type,
            "parse_quality": bundle.parse_quality,
            "vision_fallback": bool(bundle.meta.get("vision_fallback")),
            "vision_model": bundle.meta.get("vision_model"),
            "warnings": [
                warning.model_dump(mode="json") for warning in bundle.warnings
            ],
        },
    }


@st.cache_data(show_spinner=False)
def _analyze(
    file_bytes: bytes,
    file_name: str,
    existing_bills: str,
    accounting_entity: str,
    match_mode: str,
    ocr_mode: str,
    use_llm: bool,
    llm_provider: str,
    llm_model: str,
    llm_api_key: str,
    llm_base_url: str,
    llm_structured_method: str,
) -> dict:
    analysis = analyze_bytes(
        file_bytes,
        file_name,
        existing_bills=existing_bills or None,
        accounting_entity=accounting_entity or None,
        match_mode=match_mode,
        ocr_mode=ocr_mode,
        use_llm=use_llm,
        llm_provider=llm_provider or None,
        llm_model=llm_model or None,
        llm_api_key=llm_api_key or None,
        llm_base_url=llm_base_url or None,
        llm_structured_method=llm_structured_method,
    )
    return _result_payload(analysis)


@st.cache_data(show_spinner=False)
def _analyze_public_url(
    url: str,
    existing_bills: str,
    accounting_entity: str,
    match_mode: str,
    ocr_mode: str,
    use_llm: bool,
    llm_provider: str,
    llm_model: str,
    llm_api_key: str,
    llm_base_url: str,
    llm_structured_method: str,
) -> dict:
    analysis = analyze_url(
        url,
        existing_bills=existing_bills or None,
        accounting_entity=accounting_entity or None,
        match_mode=match_mode,
        ocr_mode=ocr_mode,
        use_llm=use_llm,
        llm_provider=llm_provider or None,
        llm_model=llm_model or None,
        llm_api_key=llm_api_key or None,
        llm_base_url=llm_base_url or None,
        llm_structured_method=llm_structured_method,
    )
    return _result_payload(analysis)


def _first_run_gate() -> bool:
    """Ask once which AI API to use; rules-only is an explicit option."""
    if has_saved_config():
        return True

    st.title("🚢 航运智能账单助手")
    st.subheader("首次运行：选择 AI 大模型")
    st.caption("不选择大模型也可以运行；此时只使用规则抽取，不调用任何 AI API。")

    platform = detect_platform_config()
    options = (
        ["平台当前 API", "指定 API", "不使用大模型（规则抽取）"]
        if platform is not None
        else ["指定 API", "不使用大模型（规则抽取）"]
    )
    choice = st.radio(
        "AI API 来源",
        options,
        index=0 if platform else 1,
        captions=(
            (
                "使用平台检测到的模型和 key，不需要手动填写",
                "手动选择 DeepSeek / OpenAI / Anthropic 并填写 key",
                "不调用任何大模型，只运行规则抽取",
            )
            if platform is not None
            else (
                "手动选择 DeepSeek / OpenAI / Anthropic 并填写 key",
                "不调用任何大模型，只运行规则抽取",
            )
        ),
        help="首次运行只询问一次；选择结果会保存到用户目录。",
    )
    provider = "openai"
    model = ""
    base_url = ""
    api_key = ""

    if choice == "平台当前 API" and platform is not None:
        st.info(
            f"平台检测到：provider={platform.provider}, "
            f"model={platform.model}, base_url={platform.base_url}"
        )
    elif choice == "指定 API":
        provider = st.selectbox(
            "Provider",
            PROVIDER_OPTIONS,
            help=(
                "deepseek: deepseek-chat / https://api.deepseek.com/v1\n"
                "openai: gpt-4o-mini / https://api.openai.com/v1\n"
                "anthropic: claude-sonnet-5-5 / https://api.anthropic.com"
            ),
        )
        default_model, default_base = _provider_defaults(provider)
        model = st.text_input("模型", value=default_model)
        base_url = st.text_input("Base URL", value=default_base)
        api_key = st.text_input("API Key", type="password")
    else:
        st.info("将保存为“规则抽取”模式，后续启动不会再询问。")

    if st.button("保存并开始", type="primary"):
        if choice == "平台当前 API" and platform is not None:
            save_ai_config(platform)
        elif choice == "指定 API":
            if not (model.strip() and base_url.strip() and api_key.strip()):
                st.error("模型、Base URL 和 API Key 不能为空。")
                return False
            save_ai_config(
                AIConfig(
                    provider=provider,
                    model=model.strip(),
                    base_url=base_url.strip(),
                    api_key=api_key.strip(),
                    source="custom",
                )
            )
        else:
            save_ai_config(AIConfig(provider="none", source="first_run_none"))
        st.success("配置已保存。")
        st.rerun()
    return False


def _ai_settings_sidebar() -> tuple[str, str, str, str, str, bool]:
    """First-run AI configuration: platform default or a custom API."""
    platform = detect_platform_config()
    saved = load_saved_config()

    st.header("AI API")
    if saved is not None and saved.provider == "none":
        st.caption("当前：不使用大模型（规则抽取）")
    if platform is not None:
        st.caption(
            f"平台当前 API：`{platform.provider}` / `{platform.model}` / "
            f"`{platform.base_url}`"
        )
    elif saved is None:
        st.warning("未检测到平台 API；请在首次运行配置中指定。")

    options = ["平台当前 API", "指定 API"] if platform is not None else ["指定 API"]
    source = st.radio(
        "API 来源",
        options,
        index=1 if saved is not None and platform is not None else 0,
        horizontal=True,
        captions=(
            (
                "使用平台检测到的 API；适合直接运行当前环境",
                "手动指定供应商、模型、Base URL 和 key",
            )
            if platform is not None
            else ("手动指定供应商、模型、Base URL 和 key",)
        ),
        help="平台 API 使用环境变量中的 key；指定 API 会保存到用户目录。",
    )

    if source == "平台当前 API" and platform is not None:
        provider = platform.provider
        model = platform.model
        base_url = platform.base_url
        api_key = platform.api_key
        if saved is not None and st.button("恢复平台默认"):
            clear_saved_config()
            st.rerun()
    else:
        provider_index = (
            PROVIDER_OPTIONS.index(saved.provider)
            if saved is not None and saved.provider in PROVIDER_OPTIONS
            else 0
        )
        provider = st.selectbox(
            "Provider",
            PROVIDER_OPTIONS,
            index=provider_index,
            help=(
                "deepseek 使用 OpenAI 兼容端点；openai 使用 OpenAI；"
                "anthropic 使用 Anthropic 兼容端点。"
            ),
        )
        default_model, default_base = _provider_defaults(provider)
        saved_matches_provider = saved is not None and saved.provider == provider
        model = st.text_input(
            "模型",
            value=(
                saved.model
                if saved_matches_provider and saved.model
                else os.getenv("LLM_MODEL", default_model)
            ),
        )
        base_url = st.text_input(
            "Base URL",
            value=(
                saved.base_url
                if saved_matches_provider and saved.base_url
                else os.getenv("OPENAI_BASE_URL", default_base)
            ),
        )
        api_key = st.text_input(
            "API Key",
            type="password",
            value="",
            help="留空则复用已保存的 key；配置保存在用户目录，不写入项目。",
        )
        effective_key = api_key.strip() or (
            saved.api_key if saved is not None and saved.provider == provider else ""
        )
        if st.button("保存 API 配置"):
            if model.strip() and base_url.strip() and effective_key:
                save_ai_config(
                    AIConfig(
                        provider=provider,
                        model=model.strip(),
                        base_url=base_url.strip(),
                        api_key=effective_key,
                        source="custom",
                    )
                )
                st.success("AI API 配置已保存。")
                st.rerun()
            else:
                st.error("模型、Base URL 和 API Key 不能为空。")
        if saved is not None and st.button("清除已保存配置"):
            clear_saved_config()
            st.rerun()
        api_key = effective_key

    structured_method = st.selectbox(
        "结构化输出方式",
        ("function_calling", "json_schema"),
        index=0,
        help="function_calling 兼容性更好；json_schema 需要供应商支持 JSON Schema。",
    )
    use_llm = st.checkbox(
        "使用 LangChain LLM",
        value=False,
        help="勾选后 LangChain 参与文档分类和费用语义抽取；失败会自动回退规则抽取。",
    )
    if use_llm and not (model and api_key):
        st.warning("LLM 未配置完整，将回退规则抽取。")
    return provider, model, base_url, api_key, structured_method, use_llm


def main() -> None:
    if not _first_run_gate():
        return
    st.title("🚢 航运智能账单助手")
    st.caption("多格式解析 → 结构化抽取 → 账单匹配 → AR/AP → 标准 JSON")

    with st.sidebar:
        st.header("运行配置")
        existing_bills = st.text_input(
            "已有账单 JSON",
            DEFAULT_BILLS,
            help="用于匹配和更新的历史账单文件；支持 {bills:[...]} 或 JSON 数组。",
        )
        accounting_entity = st.text_input(
            "记账主体",
            DEFAULT_ENTITY,
            help="从该主体视角判断 AR/AP；例如 IMPORTER BETA (SHANGHAI)。",
        )
        match_mode = st.radio(
            "匹配模式",
            ("strict", "enhanced"),
            horizontal=True,
            captions=(
                "严格：编号/提单/订舱/箱号四级匹配；名称或金额变化时更保守，容易进入复核",
                "增强：身份命中后允许费用名/金额变化；适合历史数据写法不一致，可能匹配出 UPDATE",
            ),
            help="strict 更符合题目四级匹配；enhanced 用于历史数据名称/金额已变化的场景。",
        )
        output_mode = st.radio(
            "下载输出模式",
            ("full", "strict"),
            horizontal=True,
            captions=(
                "完整输出：包含 source/证据/置信度/匹配过程/校验，适合调试和人工复核",
                "题目标准输出：只保留规定字段；完整审计写入同名 .audit.json",
            ),
            help="full 用于审计和演示；strict 用于按题目标准输出和系统对接。",
        )
        ocr_mode = st.radio(
            "OCR 模式",
            ("mock", "local", "api"),
            horizontal=True,
            captions=(
                "离线：不调用真实 OCR；图片不识别，文字 PDF 走本地文字层",
                "本地：解析文字 PDF/Excel/Word/EML；图片和扫描件不识别",
                "真实 OCR：PDF 先 OCR 后本地回退；图片转单页 PDF；需要公网文件 URL",
            ),
            help="mock 用于回归测试；local 用于纯文本资料；api 用于真实扫描件/图片。",
        )
        vision_ready, vision_model, vision_protocol = _vision_fallback_status()
        if vision_ready:
            st.caption(
                f"视觉兜底：已配置 `{vision_model}`（{vision_protocol}）。"
                "图片在 mock / local / api 都没有识别出内容时自动调用；结果强制复核。"
            )
        else:
            st.caption(
                "视觉兜底：未配置。图片在三种 OCR 模式都为空时不会调用大模型；"
                "请配置支持图片的 VISION_* 或首次运行 API。`VISION_FALLBACK=0` 可关闭。"
            )
        (
            llm_provider,
            llm_model,
            llm_base_url,
            llm_api_key,
            llm_structured_method,
            use_llm,
        ) = _ai_settings_sidebar()

        st.caption(
            "mock：离线；local：文字型 PDF 本地解析；api：需要公网文件 URL。"
        )

    public_urls = st.text_area(
        "输入公网文件 URL（可选，每行一个）",
        placeholder=(
            "https://example.com/invoice1.pdf\n"
            "https://example.com/invoice2.pdf"
        ),
        height=110,
        help=(
            "支持 http/https 直链，每行一个 URL。"
            "每个 URL 最多等待 OCR API 60 秒；OCR 未返回数据后自动本地解析，最后视觉模型兜底。"
        ),
    )
    uploaded = st.file_uploader(
        "上传 EML / PDF / 图片 / Excel / Word",
        type=["eml", "pdf", "png", "jpg", "jpeg", "tif", "tiff", "xlsx", "xls", "docx", "doc"],
        accept_multiple_files=True,
        help="支持 EML、PDF、PNG/JPG/TIFF、XLS/XLSX、DOC/DOCX；每个文件单独解析。",
    )

    inputs: list[tuple[str, str | object]] = []
    try:
        urls = split_urls(public_urls)
    except ParseError as exc:
        st.error(f"URL 输入错误：{exc.code}")
        st.info(exc.message)
        urls = []
    for url in urls:
        inputs.append(("url", url))
    for file in uploaded or []:
        inputs.append(("file", file))
    if not inputs:
        st.info(
            "上传文件或输入公网 URL 后开始解析。"
            "可先用 `data/fixtures/` 下的样本。"
        )
        return

    def _display_name(kind: str, item) -> str:
        if kind == "file":
            return item.name
        from urllib.parse import unquote, urlparse

        name = unquote(urlparse(str(item)).path).rsplit("/", 1)[-1]
        return name or str(item)

    tabs = st.tabs([_display_name(kind, item) for kind, item in inputs])
    for index, (tab, (kind, item)) in enumerate(zip(tabs, inputs)):
        name = _display_name(kind, item)
        stem = Path(name).stem or f"input-{index}"
        with tab:
            try:
                with st.spinner(f"解析 {name} ..."):
                    if kind == "url":
                        result = _analyze_public_url(
                            str(item),
                            existing_bills,
                            accounting_entity,
                            match_mode,
                            ocr_mode,
                            use_llm,
                            llm_provider,
                            llm_model,
                            llm_api_key,
                            llm_base_url,
                            llm_structured_method,
                        )
                    else:
                        result = _analyze(
                            item.getvalue(),
                            item.name,
                            existing_bills,
                            accounting_entity,
                            match_mode,
                            ocr_mode,
                            use_llm,
                            llm_provider,
                            llm_model,
                            llm_api_key,
                            llm_base_url,
                            llm_structured_method,
                        )
            except ParseError as exc:
                st.error(f"解析失败：{exc.code}")
                st.info(exc.message)
                if exc.code == "OCR_URL_REQUIRED":
                    st.caption(
                        "当前选择的是 api OCR 模式，但没有公网文件地址；"
                        "请设置 OCR_FILE_BASE_URL，或配置支持图片输入的视觉模型作为兜底，"
                        "也可以先切换到 mock/local 处理文字型文件。"
                    )
                elif exc.code.startswith("URL_"):
                    st.caption(
                        "请确认 URL 是可公开访问的 http/https 直链，"
                        "不是需要登录的网页、网盘预览页或已过期的签名地址。"
                    )
                continue
            except Exception as exc:  # noqa: BLE001 - show the error in the tab
                st.error(f"处理失败：{type(exc).__name__}")
                with st.expander("错误详情"):
                    st.exception(exc)
                continue

            rows = result["rows"]
            pending = sum(1 for row in rows if row["operation"] == "PENDING_REVIEW")
            creates = sum(1 for row in rows if row["operation"] == "CREATE")
            updates = sum(1 for row in rows if row["operation"] == "UPDATE")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("记录数", result["record_count"])
            col2.metric("CREATE", creates)
            col3.metric("UPDATE", updates)
            col4.metric("PENDING_REVIEW", pending)

            parse_status = result["parse_status"]
            if parse_status["vision_fallback"]:
                st.info(
                    "本次图片由视觉大模型兜底识别"
                    f"（{parse_status.get('vision_model') or 'vision'}）；"
                    "结果已强制进入 PENDING_REVIEW。"
                )
            for warning in parse_status["warnings"]:
                st.warning(
                    f"{warning.get('code', 'WARNING')}: "
                    f"{warning.get('message', '')}"
                )

            if rows:
                st.subheader("费用记录")
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.warning("未产生费用记录（可能是 OCR mock、通知类文档或未识别到费用）。")

            with st.expander("解析状态"):
                st.json(parse_status)

            st.subheader("文档分类")
            st.json(result["classification"])

            with st.expander("抽取与校验详情"):
                st.json(result["extraction"])

            st.subheader("下载")
            payload = (
                result["full_json"] if output_mode == "full" else result["strict_json"]
            )
            st.download_button(
                f"下载 {output_mode} JSON",
                data=payload,
                file_name=f"{stem}.{output_mode}.json",
                mime="application/json",
                key=f"download-{index}-{kind}-main",
            )
            st.download_button(
                "下载完整审计 JSON",
                data=result["audit_json"],
                file_name=f"{stem}.audit.json",
                mime="application/json",
                key=f"download-{index}-{kind}-audit",
            )


if __name__ == "__main__":
    main()
