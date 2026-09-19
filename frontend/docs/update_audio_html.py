import re

with open('c:/Users/Hp/TANUH-DPI-DEV/frontend/docs/audio.html', 'r', encoding='utf-8') as f:
    content = f.read()

new_content = '''
            <h1 style="margin-top:0.25rem;">Voice to EMR Documentation</h1>
            <p style="font-size:1.1rem; color:var(--text-500); margin-bottom:2rem;">Audio ASR &amp; Summarization - Complete Technical & User Documentation</p>
            
            <h1>1. Summary</h1>
<p>The Audio ASR service is a core microservice that converts medical audio dictations into highly accurate text using Indic-Conformer models. It subsequently generates structured medical summaries using abstractive NLP pipelines.</p>
<p>The service is built on a privacy-first architecture, powered by FastAPI and PyTorch.</p>
<h1>2. Service Overview</h1>
<h2>2.1 Core Features</h2>
<ul>
<li>High-accuracy ASR (Automatic Speech Recognition) for medical terminology</li>
<li>Speaker Diarization support</li>
<li>Extractive and Abstractive Summarization using HuggingFace Transformers</li>
<li>FastAPI-based REST API for seamless integration</li>
</ul>
<h2>2.2 Technology Stack</h2>
<div class="table-responsive"><table><thead><tr><th>Component</th><th>Technology</th></tr></thead><tbody><tr><td>Web Framework</td><td>FastAPI (Python 3.12)</td></tr><tr><td>Deep Learning</td><td>PyTorch</td></tr><tr><td>Audio Processing</td><td>Librosa &amp; SoundFile</td></tr><tr><td>NLP Models</td><td>HuggingFace Transformers</td></tr><tr><td>Container</td><td>Docker</td></tr></tbody></table></div>
<h1>3. API Reference</h1>
<h2>3.1 Endpoints</h2>
<p>Browser access to Swagger UI: <code>http://&lt;host&gt;:8000/docs</code></p>
<p>The primary endpoint is <code>POST /api/v1/audio/process</code> which accepts a <code>.wav</code> audio file upload and returns a JSON payload containing the full transcript, diarization timestamps, and generated summary.</p>
'''

# Replace everything inside docs-content-inner
pattern = re.compile(r'(<div class="docs-content-inner">).*?(</div>\s*</main>)', re.DOTALL)
new_html = pattern.sub(r'\1\n' + new_content + r'\n\2', content)

# Also update the <title> tag
new_html = re.sub(r'<title>.*?</title>', '<title>Audio ASR Documentation | TANUH DPI</title>', new_html)

with open('c:/Users/Hp/TANUH-DPI-DEV/frontend/docs/audio.html', 'w', encoding='utf-8') as f:
    f.write(new_html)

print('Updated audio.html successfully.')
