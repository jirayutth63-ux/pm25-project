import os
import base64
import json
from io import BytesIO
from flask import Flask, render_template, request, session, redirect, url_for
import matplotlib.pyplot as plt

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)

# --- History File ---
HISTORY_FILE = 'pm25_history.json'

# --- Model Factors ---
BASE_PM25_LEVEL, TRAFFIC_FACTOR, INDUSTRY_FACTOR, BURNING_FACTOR, WIND_DISPERSION_FACTOR = 5.0, 0.025, 1.6, 0.12, 0.08

plt.switch_backend('Agg')
plt.rcParams['font.family'] = 'sans-serif'

# --- Helper functions for history ---
def load_history():
    """Loads calculation history from a JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_history(history):
    """Saves calculation history to a JSON file."""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)


def create_pm25_bar_chart(pm25_value):
    levels = {'Good': 12.0, 'Moderate': 35.4, 'Unhealthy (Sensitive)': 55.4, 'Unhealthy': 150.4}
    level_names, thresholds = list(levels.keys()), list(levels.values())
    colors = ['#00e400', '#ffff00', '#ff7e00', '#ff0000']
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(level_names, thresholds, color=colors, width=0.5, alpha=0.7, label='AQI Level Thresholds')
    ax.axhline(y=pm25_value, color='#007bff', linestyle='--', linewidth=2.5, label=f'Latest Value: {pm25_value:.1f}')
    ax.set_ylabel('PM2.5 Concentration (µg/m³)')
    ax.set_title('Latest Value vs. AQI Levels')
    plt.xticks(rotation=10, ha="right")
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    plt.close(fig)
    return data

def create_pm25_line_chart(history):
    if not history: return None
    pm_values = [item['pm25_value'] for item in history]
    run_numbers = range(1, len(pm_values) + 1)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(run_numbers, pm_values, marker='o', linestyle='-', color='#dc3545', label='PM2.5 Trend')
    for i, txt in enumerate(pm_values):
        ax.annotate(f'{txt:.1f}', (run_numbers[i], pm_values[i]), textcoords="offset points", xytext=(0,10), ha='center')
    ax.set_ylabel('PM2.5 Concentration (µg/m³)')
    ax.set_xlabel('Simulation Run Number')
    ax.set_title('PM2.5 Trend from Simulation History')
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    ax.set_xticks(run_numbers)
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    plt.close(fig)
    return data

def calculate_and_analyze_pm25(traffic, industry, burning, wind):
    total_sources = BASE_PM25_LEVEL + (traffic * TRAFFIC_FACTOR) + (industry * INDUSTRY_FACTOR) + (burning * BURNING_FACTOR)
    wind_dispersion = 1 + (wind * WIND_DISPERSION_FACTOR)
    calculated_pm25 = total_sources / wind_dispersion
    if 0 <= calculated_pm25 <= 12.0: level, msg, css = "ดี", "คุณภาพอากาศดีมาก", "good"
    elif 12.1 <= calculated_pm25 <= 35.4: level, msg, css = "ปานกลาง", "ผู้ที่ต้องดูแลสุขภาพเป็นพิเศษควรลดเวลาทำกิจกรรมกลางแจ้ง", "fair"
    elif 35.5 <= calculated_pm25 <= 55.4: level, msg, css = "เริ่มมีผลกระทบต่อสุขภาพ", "กลุ่มเสี่ยงควรลดเวลาทำกิจกรรมกลางแจ้ง", "poor"
    else: level, msg, css = "มีผลกระทบต่อสุขภาพ", "ทุกคนควรเฝ้าระวังและลดเวลาการทำกิจกรรมกลางแจ้ง", "poor"
    return {"calculated_pm25": calculated_pm25, "level": level, "message": msg, "css_class": css}

def generate_analytical_summary(base, scenario, base_res, scenario_res):
    parts = []
    if scenario['traffic'] > base['traffic']: parts.append("ปริมาณรถที่เพิ่มขึ้น")
    if scenario['burning'] > base['burning']: parts.append("การเผาที่เพิ่มขึ้น")
    if scenario['wind'] < base['wind']: parts.append("ความเร็วลมที่ลดลง")
    if not parts: return None
    change = ((scenario_res['calculated_pm25'] - base_res['calculated_pm25']) / base_res['calculated_pm25']) * 100 if base_res['calculated_pm25'] > 0 else 0
    return f"จากการจำลองเมื่อเงื่อนไขเปลี่ยน ({', '.join(parts)}) ส่งผลให้ PM2.5 เปลี่ยนแปลงประมาณ {change:.1f}%"

def generate_detailed_analysis(inputs, result):
    analysis_points = []
    sources = {'การจราจร': inputs['traffic'] * TRAFFIC_FACTOR, 'ภาคอุตสาหกรรม': inputs['industry'] * INDUSTRY_FACTOR, 'การเผาในที่โล่ง': inputs['burning'] * BURNING_FACTOR}
    if sum(sources.values()) > 0: analysis_points.append(f"ปัจจัยหลักที่ส่งผลต่อค่าฝุ่นในสถานการณ์นี้คือ '<strong>{max(sources, key=sources.get)}</strong>'.")
    if inputs['wind'] < 5 and result['calculated_pm25'] > 12.0: analysis_points.append("ความเร็วลมที่ค่อนข้างต่ำทำให้มลพิษกระจายตัวได้ไม่ดี ส่งผลให้ค่า PM2.5 สูงขึ้น")
    current_pm25 = result['calculated_pm25']
    if inputs['wind'] < 15 and current_pm25 > 35.4:
        hypo_wind = inputs['wind'] + 8
        hypo_inputs = inputs.copy(); hypo_inputs['wind'] = hypo_wind
        total_sources = BASE_PM25_LEVEL + (hypo_inputs['traffic'] * TRAFFIC_FACTOR) + (hypo_inputs['industry'] * INDUSTRY_FACTOR) + (hypo_inputs['burning'] * BURNING_FACTOR)
        hypo_pm25 = total_sources / (1 + (hypo_inputs['wind'] * WIND_DISPERSION_FACTOR))
        if hypo_pm25 < current_pm25:
            reduc_pct = ((current_pm25 - hypo_pm25) / current_pm25) * 100
            analysis_points.append(f"หากความเร็วลมเพิ่มขึ้นเป็น <strong>{hypo_wind:.1f} km/h</strong> คาดว่าค่า PM2.5 จะลดลงประมาณ <strong>{reduc_pct:.1f}%</strong>.")
    return analysis_points if analysis_points else None

@app.route("/")
def home(): return render_template('home.html')

@app.route("/members")
def members():
    group_members = [
        {'name': 'นาย ธนพนธ์ คำนนท์', 'role': 'ทำหน้าโฮมและการประยุกต์ Python', 'image': 'images/member1.jpg'},
        {'name': 'นาย จิรายุทธ ทองสันต์', 'role': 'ทำหน้า Members และการประยุกต์ Python', 'image': 'css/images/jirayut.png'},
        {'name': 'นาย สิริราช คุณความดี', 'role': 'ทำหน้า การประยุกต์ใช้ Python', 'image': 'images/sirirat.png'}
    ]
    return render_template('members.html', members=group_members)

@app.route("/python-apps", methods=["GET", "POST"])
def python_apps():
    result, summary, bar_graph, line_graph, detailed_analysis = None, None, None, None, None
    inputs = session.get('base_inputs', {})
    history = load_history()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "clear":
            session.pop('base_inputs', None)
            save_history([])
            return redirect(url_for('python_apps'))
        
        try:
            if 'scenario' in action:
                if 'base_inputs' not in session:
                    return redirect(url_for('python_apps')) 
                input_source = session.get('base_inputs')
            else:
                input_source = request.form

            current_inputs = {k: float(input_source.get(k, 0)) for k in ['traffic', 'industry', 'burning', 'wind']}
            inputs = current_inputs.copy()

            if action == 'calculate':
                session['base_inputs'] = current_inputs
            elif action == "scenario_traffic":
                inputs['traffic'] *= 1.5
            elif action == "scenario_burning":
                inputs['burning'] += 50
            elif action == "scenario_wind":
                inputs['wind'] *= 0.5

            result = calculate_and_analyze_pm25(**inputs)
            
            history.append({**inputs, "pm25_value": result['calculated_pm25'], "level": result['level']})
            save_history(history)
            
            detailed_analysis = generate_detailed_analysis(inputs, result)

            if 'scenario' in action and 'base_inputs' in session:
                base_result = calculate_and_analyze_pm25(**session['base_inputs'])
                summary = generate_analytical_summary(session['base_inputs'], inputs, base_result, result)

            bar_graph = create_pm25_bar_chart(result['calculated_pm25'])
            line_graph = create_pm25_line_chart(history)
            session.modified = True

        except (ValueError, TypeError, KeyError):
            return redirect(url_for('python_apps'))

    elif request.method == "GET" and history:
        last_run = history[-1]
        last_inputs = {k: v for k, v in last_run.items() if k in ['traffic', 'industry', 'burning', 'wind']}
        result = calculate_and_analyze_pm25(**last_inputs)
        detailed_analysis = generate_detailed_analysis(last_inputs, result)
        bar_graph = create_pm25_bar_chart(result['calculated_pm25'])
        line_graph = create_pm25_line_chart(history)
        inputs = last_inputs

    return render_template('python_apps.html', pm25_result=result, pm25_inputs=inputs, history=history, 
                           analysis_summary=summary, bar_chart_graph=bar_graph, line_chart_graph=line_graph,
                           detailed_analysis=detailed_analysis)
