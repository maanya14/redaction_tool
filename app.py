"""
app.py
======
Basic Streamlit UI for the PII redaction tool.

Run with:
    streamlit run app.py

Lets you upload a .docx, runs the existing pii_redactor pipeline on it
(no changes to the detection/redaction logic itself), and gives you the
redacted .docx and a CSV audit log to download.
"""

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

import streamlit as st

from pii_redactor import redact_docx
from pii_redactor.fake_map import FakeMapper

st.set_page_config(page_title="PII Redactor", page_icon="🕵️", layout="centered")

st.title("🕵️ PII Redaction Tool")
st.write(
    "Upload a `.docx` file. It will be scanned for names, emails, phone "
    "numbers, company names, addresses, SSNs, credit card numbers, dates "
    "of birth, and IP addresses, and each one will be replaced with a "
    "realistic fake value (the same fake value every time it repeats)."
)

with st.sidebar:
    st.header("Options")
    seed = st.number_input(
        "Fake-value seed",
        min_value=0,
        value=42,
        help="Change this to get a different set of fake replacement values "
             "for the same input file.",
    )
    st.caption(
        "This runs the same detection/redaction code as the CLI "
        "(`redact_pii.py`) — this is just a UI on top of it."
    )

uploaded = st.file_uploader("Upload a .docx file", type=["docx"])

if uploaded is not None:
    if st.button("Redact PII", type="primary"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / uploaded.name
            output_path = tmp_path / f"{input_path.stem}_REDACTED.docx"
            input_path.write_bytes(uploaded.getvalue())

            with st.spinner("Scanning and redacting..."):
                mapper = FakeMapper(seed=int(seed))
                mapper, log = redact_docx(str(input_path), str(output_path), mapper=mapper)

            st.success(f"Done — {len(log)} redactions made.")

            if log:
                counts = Counter(row["label"] for row in log)
                st.subheader("Redactions by category")
                st.table(
                    {"Category": list(counts.keys()), "Count": list(counts.values())}
                )
            else:
                st.info("No PII was detected in this document.")

            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "⬇️ Download redacted .docx",
                    data=output_path.read_bytes(),
                    file_name=output_path.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
            with col2:
                csv_buffer = io.StringIO()
                writer = csv.DictWriter(csv_buffer, fieldnames=["label", "original", "fake"], extrasaction="ignore")
                writer.writeheader()
                writer.writerows(log)
                st.download_button(
                    "⬇️ Download audit log (.csv)",
                    data=csv_buffer.getvalue(),
                    file_name=f"{input_path.stem}_audit_log.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            with st.expander("Preview redactions made"):
                st.dataframe(
                    [{"Category": r["label"], "Original": r["original"], "Replaced with": r["fake"]} for r in log],
                    use_container_width=True,
                )
else:
    st.caption("Waiting for a file to be uploaded.")
