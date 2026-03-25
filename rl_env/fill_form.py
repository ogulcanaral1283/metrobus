"""Fill CMPE491 Project Proposal Form with Metrobus RL project details."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from docx import Document
from copy import deepcopy

INPUT = r'c:\Users\ogulcan\Desktop\metrobus\CMPE491_Project_Proposal_Form (1) (4) (2).docx'
OUTPUT = r'c:\Users\ogulcan\Desktop\metrobus\CMPE491_Project_Proposal_FILLED.docx'

doc = Document(INPUT)

# ============================================================
# 1. TITLE
# ============================================================
for para in doc.paragraphs:
    if "Title of The Project" in para.text:
        for run in para.runs:
            if "Title of The Project" in run.text:
                run.text = "Title of The Project : \tSmart Metrobus Fleet Management Using Multi-Agent Reinforcement Learning (MAPPO)"
                break
        break

# ============================================================
# 2. DESCRIPTION (P15 sonrasi bos paragraflar)
# ============================================================
description = """This project develops an intelligent fleet management system for Istanbul's Metrobus Bus Rapid Transit (BRT) line using Multi-Agent Proximal Policy Optimization (MAPPO), a state-of-the-art multi-agent reinforcement learning algorithm. The Istanbul Metrobus carries over 900,000 passengers daily across a 52km dedicated corridor with 44 stations, making it one of the busiest BRT systems in the world. A critical operational challenge is "bus bunching" — where vehicles cluster together, causing long gaps followed by overcrowded buses.

Our system models each metrobus as an independent RL agent that observes its local state (position, speed, headway to neighbors, station proximity, time of day) and selects actions: normal cruise, hold at station, speed up, or skip stop. Using the CTDE (Centralized Training, Decentralized Execution) paradigm, a shared actor network enables parameter-efficient training while a centralized critic uses global state information during training only.

The environment is built as a custom OpenAI Gymnasium simulation using real Istanbul Metrobus route data extracted from OpenStreetMap (Overpass API), including actual GPS coordinates, station locations, and platform capacities. The physics engine implements the Intelligent Driver Model (IDM) for realistic car-following behavior, and a station finite state machine (FSM) handles passenger boarding, dwell times, and slot-based platform queuing.

Key technical contributions include: (1) A curriculum learning approach with two training phases — first with simplified fixed dwell times for stable base policy learning, then fine-tuning with realistic passenger-based dwell dynamics; (2) Route segmentation for dense traffic training scenarios; (3) A normalized cooperative reward function combining headway regularity (CV-based), bunching penalties, speed targets, and operational constraints; (4) A real-time web dashboard built with React, TypeScript, and Leaflet for live simulation visualization and vehicle control.

The trained ONNX model will be integrated into the existing web-based dashboard, enabling real-time inference and visualization of the RL agent's decisions on an interactive map of Istanbul."""

# Find description paragraph and fill subsequent empty paragraphs
desc_idx = None
for i, para in enumerate(doc.paragraphs):
    if "Description of the Project" in para.text:
        desc_idx = i
        break

if desc_idx is not None:
    # Write description into the first empty paragraph after the description header
    for i in range(desc_idx + 1, min(desc_idx + 12, len(doc.paragraphs))):
        if not doc.paragraphs[i].text.strip():
            doc.paragraphs[i].text = description
            break

# ============================================================
# 3. WORK PACKAGES TABLE
# ============================================================
work_packages = [
    ("Literature Review & System Design",
     "3 weeks",
     "All Students"),
    ("Environment Development (Gymnasium, IDM Physics, Station FSM)",
     "4 weeks",
     "All Students"),
    ("Route Data Pipeline (OSM/Overpass API extraction, linearization, station slots)",
     "2 weeks",
     "All Students"),
    ("MAPPO Agent Implementation (Actor-Critic networks, PPO training loop, GAE)",
     "4 weeks",
     "All Students"),
    ("Reward Engineering & Curriculum Learning (normalization, two-phase training)",
     "3 weeks",
     "All Students"),
    ("Web Dashboard Integration (React/TypeScript, Leaflet map, real-time visualization)",
     "4 weeks",
     "All Students"),
    ("ONNX Export & Real-time Inference Integration",
     "2 weeks",
     "All Students"),
    ("Testing, Evaluation & Documentation",
     "3 weeks",
     "All Students"),
]

table0 = doc.tables[0]
for i, (desc, duration, responsible) in enumerate(work_packages):
    row = table0.rows[i + 1]  # Skip header
    row.cells[1].text = desc
    row.cells[2].text = duration
    row.cells[3].text = responsible

# ============================================================
# 4. TECHNOLOGIES TABLE
# ============================================================
tech_table = doc.tables[1]

# Row 1: Programming Language and platform
tech_table.rows[1].cells[2].text = "Python 3.13 (RL environment, training, inference), TypeScript (web dashboard, simulation engine), JavaScript/Node.js (data export scripts). Platform: Windows/Linux with NVIDIA CUDA GPU support."

# Row 2: Library & Frameworks
tech_table.rows[2].cells[2].text = "PyTorch 2.6 (MAPPO neural networks, CUDA acceleration), OpenAI Gymnasium (RL environment interface), NumPy (numerical computation), ONNX/ONNXRuntime (model export for real-time inference), TensorBoard (training visualization), python-docx (document generation)."

# Row 3: Database & Storage
tech_table.rows[3].cells[2].text = "JSON files for route/station data storage (route_network.json, station_slots.json). No traditional database required — all data is file-based for simulation."

# Row 4: Networking & communication
tech_table.rows[4].cells[2].text = "REST API (Express.js backend serves simulation state to React frontend). WebSocket consideration for real-time dashboard updates. Overpass API (OpenStreetMap) for geographic route data extraction."

# Row 5: Web App - Frontend
tech_table.rows[5].cells[2].text = "React 18 with TypeScript, Leaflet.js (interactive map visualization), Vite (build tool), TailwindCSS (styling)."

# Row 6: Web App - Backend
tech_table.rows[6].cells[2].text = "Node.js with Express.js (serves simulation API), TypeScript (shared simulation engine between frontend and backend)."

# Row 7: Web App - Web server
tech_table.rows[7].cells[2].text = "Vite dev server (development), Docker with Nginx (production deployment)."

# Row 8: Mobile App - N/A
tech_table.rows[8].cells[2].text = "N/A — The system is web-based with responsive design for mobile access."

# Row 9: 3D Library - N/A
tech_table.rows[9].cells[2].text = "N/A — 2D map-based visualization using Leaflet.js with custom vehicle markers and route overlays."

# Row 10: Research - Dataset
tech_table.rows[10].cells[2].text = "Custom dataset: Istanbul Metrobus route data extracted from OpenStreetMap via Overpass API — 52km corridor, 44 stations (gidis) / 43 stations (donus), 1064 GPS coordinate segments. Station platform data (slot counts, platform lengths in meters) collected from field measurements. Passenger demand profiles based on Istanbul Metropolitan Municipality (IBB) public transit statistics."

# Row 11: Research - Article
tech_table.rows[11].cells[2].text = 'Yu, C., Velu, A., et al. "The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games" (NeurIPS 2022) — MAPPO algorithm. Treiber, M., Hennecke, A., Helbing, D. "Congested Traffic States in Empirical Observations and Microscopic Simulations" — Intelligent Driver Model (IDM) for vehicle following.'

# Row 12: Research - Algorithm
tech_table.rows[12].cells[2].text = "Multi-Agent Proximal Policy Optimization (MAPPO) with CTDE paradigm. Architecture: Shared Actor network (MLP, 64 hidden units, Categorical policy) for decentralized execution + Centralized Critic network (MLP, 256 hidden units) using global state. Training: PPO with clipped surrogate objective, GAE (lambda=0.95), entropy regularization, curriculum learning (2 phases). Vehicle physics: Intelligent Driver Model (IDM) for realistic car-following dynamics."

# Row 13-15: Embedded - N/A
tech_table.rows[13].cells[2].text = "N/A"
tech_table.rows[14].cells[2].text = "N/A"
tech_table.rows[15].cells[2].text = "N/A"

# Row 16: Other
tech_table.rows[16].cells[2].text = "Docker & Docker Compose (containerized deployment), Git/GitHub (version control), TensorBoard (training monitoring), NVIDIA CUDA Toolkit (GPU-accelerated training on RTX 5070 Ti)."

# ============================================================
# SAVE
# ============================================================
doc.save(OUTPUT)
print(f"Doldurulmus form kaydedildi: {OUTPUT}")
print("Ogrenci isimlerini, advisor ve imza kisimlarini siz doldurun.")
