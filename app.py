import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, timedelta
import os
from io import StringIO
import shutil

# --- CONFIGURATION ---
DB_NAME = 'vikrant_tracker_v2.db'
DB_BACKUP_DIR = 'backups'

# Scoring configuration
SCORE_CONFIG = {
    'coded_today': 30,
    'no_junk_food': 20,
    'workout_done': 10,
    'pushups_max': 30,
    'study_hours_max': 10,
}

# Emoji configuration
EMOJI_CONFIG = {
    'coded_today': '💻',
    'no_junk_food': '🥗',
    'workout_done': '🏋️',
    'pushups': '💪',
    'study_hours': '📚',
    'water_liters': '💧',
    'score': '🏆',
    'notes': '📝',
}

# --- BACKEND ---
def init_db():
    """Initialize database with schema, create backup directory."""
    try:
        os.makedirs(DB_BACKUP_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS daily_log
                     (log_date TEXT PRIMARY KEY, 
                      pushups INTEGER,
                      study_hours REAL, 
                      water_liters REAL,
                      coded_today INTEGER,
                      no_junk_food INTEGER,
                      workout_done INTEGER,
                      notes TEXT,
                      victory_score INTEGER)''')
        
        # Migration: Add missing columns if they don't exist
        c.execute("PRAGMA table_info(daily_log)")
        columns = [col[1] for col in c.fetchall()]
        
        # Remove took_supplements if it exists (migration from old schema)
        if 'took_supplements' in columns:
            c.execute('''
                CREATE TABLE daily_log_new (
                    log_date TEXT PRIMARY KEY,
                    pushups INTEGER,
                    study_hours REAL,
                    water_liters REAL,
                    coded_today INTEGER,
                    no_junk_food INTEGER,
                    workout_done INTEGER,
                    notes TEXT,
                    victory_score INTEGER
                )
            ''')
            c.execute('''
                INSERT INTO daily_log_new 
                SELECT log_date, pushups, study_hours, water_liters, 
                       coded_today, no_junk_food, workout_done, notes, victory_score 
                FROM daily_log
            ''')
            c.execute('DROP TABLE daily_log')
            c.execute('ALTER TABLE daily_log_new RENAME TO daily_log')
        
        # Add workout_done if it doesn't exist (migration from old schema)
        if 'workout_done' not in columns:
            c.execute("ALTER TABLE daily_log ADD COLUMN workout_done INTEGER DEFAULT 0")
        
        # Add notes if it doesn't exist
        if 'notes' not in columns:
            c.execute("ALTER TABLE daily_log ADD COLUMN notes TEXT DEFAULT ''")
        
        conn.commit()
        conn.close()
        auto_backup_db()
    except Exception as e:
        st.error(f"Database initialization error: {e}")

def auto_backup_db():
    """Auto-backup database every time the app runs."""
    try:
        if os.path.exists(DB_NAME):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(DB_BACKUP_DIR, f"backup_{timestamp}.db")
            shutil.copy(DB_NAME, backup_file)
            # Keep only last 10 backups
            backups = sorted(os.listdir(DB_BACKUP_DIR))
            if len(backups) > 10:
                for old_backup in backups[:-10]:
                    os.remove(os.path.join(DB_BACKUP_DIR, old_backup))
    except Exception as e:
        st.warning(f"Backup error: {e}")

def get_current_week_dates(offset_weeks=0):
    """Returns a list of dates for a week (Sunday to Saturday), with optional week offset."""
    today = date.today()
    today = today - timedelta(weeks=offset_weeks)
    days_to_subtract = (today.weekday() + 1) % 7
    start_sunday = today - timedelta(days=days_to_subtract)
    
    week_dates = []
    for i in range(7):
        week_dates.append(start_sunday + timedelta(days=i))
    return week_dates, start_sunday

@st.cache_data
def get_display_data(offset_weeks=0):
    """Get data for the specified week with caching."""
    conn = sqlite3.connect(DB_NAME)
    
    # 1. Get standard week dates (Sun -> Sat)
    week_dates, start_sunday = get_current_week_dates(offset_weeks)
    # Convert to strings for merging
    str_dates = [d.isoformat() for d in week_dates]
    
    try:
        df_db = pd.read_sql_query("SELECT * FROM daily_log", conn)
    except:
        df_db = pd.DataFrame()
    conn.close()

    # 2. Create Master DataFrame
    df_week = pd.DataFrame({'log_date': str_dates})
    
    if not df_db.empty:
        df_final = pd.merge(df_week, df_db, on='log_date', how='left')
    else:
        df_final = df_week

    # 3. Defaults for missing data
    required_cols = {
        'coded_today': False, 'no_junk_food': False, 'workout_done': False,
        'pushups': 0, 'study_hours': 0.0, 'water_liters': 0.0, 'victory_score': 0, 'notes': ''
    }
    for col, default_val in required_cols.items():
        if col not in df_final.columns:
            df_final[col] = default_val

    df_final.fillna(0, inplace=True)
    
    # 4. Fix Boolean Types
    bool_cols = ['coded_today', 'no_junk_food', 'workout_done']
    for col in bool_cols:
        df_final[col] = df_final[col].astype(bool)

    # 5. FORMATTING FOR DISPLAY
    # We add a 'Day' column formatted as "09 JAN FRI"
    # We keep 'log_date' hidden to identify the row accurately
    df_final['Day'] = df_final['log_date'].apply(
        lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%d %b %a").upper()
    )
    
    # Move 'Day' to the front
    cols = ['Day', 'log_date'] + [c for c in df_final.columns if c not in ['Day', 'log_date']]
    df_final = df_final[cols]
    
    return df_final, start_sunday

def validate_numeric_input(value, min_val=0, max_val=None):
    """Validate numeric input to prevent invalid data."""
    try:
        num = float(value) if isinstance(value, str) else value
        if num < min_val:
            return min_val
        if max_val and num > max_val:
            return max_val
        return num
    except:
        return min_val

def save_grid_changes(edited_df):
    """Save grid changes with validation and error handling."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today_str = date.today().isoformat()
    
    ignored_future = False
    saved_count = 0

    for index, row in edited_df.iterrows():
        try:
            # --- FUTURE DATE PROTECTION ---
            if row['log_date'] > today_str:
                ignored_future = True
                continue 

            # --- INPUT VALIDATION ---
            pushups = validate_numeric_input(row['pushups'], 0, 200)
            study_hours = validate_numeric_input(row['study_hours'], 0, 24)
            water_liters = validate_numeric_input(row['water_liters'], 0, 20)

            # --- SCORING ---
            score = 0
            if row['coded_today']: score += SCORE_CONFIG['coded_today']
            if row['no_junk_food']: score += SCORE_CONFIG['no_junk_food']
            if row['workout_done']: score += SCORE_CONFIG['workout_done']
            score += min(pushups * 1, SCORE_CONFIG['pushups_max'])
            score += min(study_hours * 5, SCORE_CONFIG['study_hours_max'])
            final_score = min(score, 100)
            
            c.execute('''INSERT OR REPLACE INTO daily_log 
                         (log_date, pushups, study_hours, water_liters, coded_today, no_junk_food, workout_done, notes, victory_score)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (row['log_date'], int(pushups), study_hours, water_liters, 
                       int(row['coded_today']), int(row['no_junk_food']), int(row['workout_done']), 
                       str(row.get('notes', '')), final_score))
            saved_count += 1
        except Exception as e:
            st.error(f"Error saving row {index}: {e}")
    
    try:
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Database commit error: {e}")
        return False
    
    if ignored_future:
        st.toast("⚠️ Future dates were ignored (Locked).", icon="🔒")
    st.success(f"✅ {saved_count} entries updated!")
    return True

def get_streak_data(habit_col):
    """Calculate current and longest streak for a habit."""
    try:
        conn = sqlite3.connect(DB_NAME)
        df_all = pd.read_sql_query("SELECT log_date, {} FROM daily_log ORDER BY log_date".format(habit_col), conn)
        conn.close()
        
        if df_all.empty:
            return 0, 0
        
        df_all['log_date'] = pd.to_datetime(df_all['log_date'])
        df_all[habit_col] = df_all[habit_col].astype(bool)
        
        # Calculate streaks
        current_streak = 0
        longest_streak = 0
        temp_streak = 0
        
        for idx, row in df_all.iterrows():
            if row[habit_col]:
                temp_streak += 1
                longest_streak = max(longest_streak, temp_streak)
            else:
                temp_streak = 0
        
        # Check if current streak is active (today or recent)
        last_date = df_all['log_date'].iloc[-1]
        if (date.today() - last_date.date()).days <= 1:
            current_streak = temp_streak
        
        return current_streak, longest_streak
    except Exception as e:
        st.error(f"Streak calculation error: {e}")
        return 0, 0

def get_completion_stats(df):
    """Calculate completion statistics for the week."""
    try:
        stats = {
            'total_score': int(df['victory_score'].sum()),
            'avg_score': round(df['victory_score'].mean(), 1),
            'completed_days': len(df[df['victory_score'] > 0]),
            'coded_days': df['coded_today'].sum(),
            'clean_days': df['no_junk_food'].sum(),
            'workout_days': df['workout_done'].sum(),
            'total_pushups': int(df['pushups'].sum()),
            'total_study': round(df['study_hours'].sum(), 1),
            'total_water': round(df['water_liters'].sum(), 1),
        }
        return stats
    except Exception as e:
        st.error(f"Stats calculation error: {e}")
        return {}

def export_to_csv(df, filename="habit_tracker.csv"):
    """Generate CSV export data."""
    try:
        csv = df.to_csv(index=False)
        return csv
    except Exception as e:
        st.error(f"Export error: {e}")
        return None

# --- FRONTEND ---
st.set_page_config(page_title="Vikrant's Supreme Tracker", page_icon="💪", layout="wide", initial_sidebar_state="expanded")

# --- SOLO LEVELING THEME CSS ---
st.markdown("""
<style>
    /* Main Background */
    .main {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
    }
    
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1028 0%, #1a1a3e 100%);
        border-right: 2px solid #7c3aed;
    }
    
    /* Text Colors */
    h1, h2, h3, h4, h5, h6 {
        color: #e0e0ff;
        text-shadow: 0 0 20px rgba(124, 58, 237, 0.5);
        font-family: 'Arial', sans-serif;
        font-weight: 700;
    }
    
    p, label, span {
        color: #c0c0ff;
    }
    
    /* Metric Cards */
    [data-testid="metric-container"] {
        background: linear-gradient(135deg, #1a0033 0%, #2d0052 100%);
        border: 1px solid #7c3aed;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 0 20px rgba(124, 58, 237, 0.3), inset 0 0 20px rgba(124, 58, 237, 0.1);
    }
    
    /* Buttons */
    button {
        background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%) !important;
        color: #ffffff !important;
        border: 1px solid #d8b4fe !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 0 15px rgba(168, 85, 247, 0.4) !important;
        text-shadow: 0 0 10px rgba(0, 0, 0, 0.5) !important;
    }
    
    button:hover {
        background: linear-gradient(135deg, #a855f7 0%, #d946ef 100%) !important;
        box-shadow: 0 0 25px rgba(168, 85, 247, 0.6) !important;
    }
    
    /* Input Fields */
    input, textarea, select {
        background: #1a0033 !important;
        color: #e0e0ff !important;
        border: 1px solid #7c3aed !important;
        border-radius: 6px !important;
        box-shadow: 0 0 10px rgba(124, 58, 237, 0.2) !important;
    }
    
    input:focus {
        border-color: #d946ef !important;
        box-shadow: 0 0 20px rgba(217, 70, 239, 0.5) !important;
    }
    
    /* Data Editor */
    [data-testid="dataframe"] {
        background: #0f1028 !important;
        border: 1px solid #7c3aed !important;
        border-radius: 8px !important;
        box-shadow: 0 0 20px rgba(124, 58, 237, 0.2) !important;
    }
    
    /* Tabs */
    [data-testid="stTabs"] [role="tablist"] {
        border-bottom: 2px solid #7c3aed;
    }
    
    [data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%);
        color: #ffffff;
        border-radius: 6px 6px 0 0;
    }
    
    /* Divider */
    hr {
        border: none;
        border-top: 2px solid #7c3aed;
        margin: 30px 0;
        box-shadow: 0 0 20px rgba(124, 58, 237, 0.3);
    }
    
    /* Toast/Success Messages */
    .stAlert {
        background: linear-gradient(135deg, #1a3a1a 0%, #2d5a2d 100%) !important;
        border: 1px solid #4ade80 !important;
        border-radius: 8px !important;
        box-shadow: 0 0 20px rgba(74, 222, 128, 0.3) !important;
    }
    
    .stAlert[kind="error"] {
        background: linear-gradient(135deg, #3a1a1a 0%, #5a2d2d 100%) !important;
        border: 1px solid #ef4444 !important;
        box-shadow: 0 0 20px rgba(239, 68, 68, 0.3) !important;
    }
    
    .stAlert[kind="warning"] {
        background: linear-gradient(135deg, #3a2a1a 0%, #5a4a2d 100%) !important;
        border: 1px solid #f97316 !important;
        box-shadow: 0 0 20px rgba(249, 115, 22, 0.3) !important;
    }
    
    /* Checkbox */
    [type="checkbox"] {
        accent-color: #a855f7 !important;
    }
    
    /* Chart Container */
    .stChart {
        border: 1px solid #7c3aed;
        border-radius: 8px;
        padding: 15px;
        background: rgba(26, 0, 51, 0.5);
        box-shadow: 0 0 15px rgba(124, 58, 237, 0.2);
    }
    
    /* Session State */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%) !important;
        color: #000 !important;
    }
</style>
""", unsafe_allow_html=True)

init_db()

st.title("📅 Weekly Habit Sheet")

# Add decorative header
st.markdown("""
<div style='text-align: center; margin-bottom: 30px;'>
    <h2 style='color: #d946ef; text-shadow: 0 0 30px rgba(217, 70, 239, 0.8); font-size: 2.5em;'>
        ⚡ HUNTER'S QUEST LOG ⚡
    </h2>
    <p style='color: #a0a0ff; font-size: 1.1em; margin-top: -10px;'>
        Become a stronger version of yourself. Level up your habits.
    </p>
</div>
""", unsafe_allow_html=True)

# --- SIDEBAR: WEEK NAVIGATION & CONTROLS ---
with st.sidebar:
    st.markdown("""
    <div style='text-align: center; padding: 20px 0;'>
        <h3 style='color: #d946ef; text-shadow: 0 0 20px rgba(217, 70, 239, 0.6);'>⚔️ MISSION CONTROL</h3>
    </div>
    """, unsafe_allow_html=True)
    
    st.subheader("🗓️ Navigate Weeks")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Previous", use_container_width=True):
            st.session_state.week_offset = st.session_state.get('week_offset', 0) + 1
    with col2:
        if st.button("Current →", use_container_width=True):
            st.session_state.week_offset = 0
    
    week_offset = st.session_state.get('week_offset', 0)
    
    st.divider()
    st.markdown("<h4 style='color: #a855f7;'>📊 Dashboard Options</h4>", unsafe_allow_html=True)
    show_history = st.checkbox("📈 Monthly View", value=False)
    show_streaks = st.checkbox("🔥 Streak Tracker", value=True)

# 1. Load Data
df, week_start = get_display_data(week_offset)
week_label = week_start.strftime("%d %b %Y")

st.markdown(f"""
<div style='background: linear-gradient(135deg, #2d0052 0%, #1a0033 100%); 
            border: 2px solid #7c3aed; border-radius: 10px; padding: 20px; 
            margin-bottom: 20px; box-shadow: 0 0 20px rgba(124, 58, 237, 0.3);'>
    <h3 style='color: #d946ef; margin: 0; text-shadow: 0 0 15px rgba(217, 70, 239, 0.6);'>
        📅 Week of {week_label}
    </h3>
</div>
""", unsafe_allow_html=True)

# 2. Grid Config
column_config = {
    "Day": st.column_config.TextColumn("Day", disabled=True),
    "log_date": None,
    "coded_today": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['coded_today']} Coded?", default=False),
    "no_junk_food": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['no_junk_food']} No Junk", default=False),
    "workout_done": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['workout_done']} Workout", default=False),
    "pushups": st.column_config.NumberColumn(f"{EMOJI_CONFIG['pushups']} Pushups", format="%d", min_value=0, max_value=200),
    "study_hours": st.column_config.NumberColumn(f"{EMOJI_CONFIG['study_hours']} Study", format="%.1f", min_value=0, max_value=24),
    "water_liters": st.column_config.NumberColumn(f"{EMOJI_CONFIG['water_liters']} Water", format="%.1f", min_value=0, max_value=20),
    "notes": st.column_config.TextColumn(f"{EMOJI_CONFIG['notes']} Notes", default=""),
    "victory_score": st.column_config.ProgressColumn(f"{EMOJI_CONFIG['score']} Score", format="%d%%", min_value=0, max_value=100),
}

with st.form("weekly_form"):
    # We display the grid
    edited_df = st.data_editor(
        df, 
        column_config=column_config, 
        num_rows="fixed", 
        hide_index=True, 
        use_container_width=True
    )
    
    col1, col2, col3 = st.columns(3)
    with col1:
        save_clicked = st.form_submit_button("💾 Save Changes", use_container_width=True)
    with col2:
        export_clicked = st.form_submit_button("📥 Export CSV", use_container_width=True)
    with col3:
        reset_clicked = st.form_submit_button("🔄 Reset Week", use_container_width=True)
    
     if save_clicked:
        # We removed the extra checkbox. The "Save Changes" button IS the confirmation.
        if save_grid_changes(edited_df):
            st.session_state.week_offset = 0
            st.cache_data.clear()
            st.rerun()
    
    if export_clicked:
        csv_data = export_to_csv(edited_df)
        if csv_data:
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"habit_tracker_{week_start.isoformat()}.csv",
                mime="text/csv"
            )
    
    if reset_clicked:
        if st.checkbox("Confirm reset? This cannot be undone."):
            # Would need to implement reset logic
            st.toast("Reset not implemented yet", icon="⚠️")

# --- WEEKLY STATISTICS ---
st.divider()
st.markdown("""
<div style='text-align: center; margin: 20px 0;'>
    <h2 style='color: #d946ef; text-shadow: 0 0 20px rgba(217, 70, 239, 0.6);'>📊 WEEKLY PERFORMANCE</h2>
</div>
""", unsafe_allow_html=True)

if not edited_df.empty:
    stats = get_completion_stats(edited_df)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Score", f"{stats.get('total_score', 0)}", delta=None)
    with col2:
        st.metric("Avg Score", f"{stats.get('avg_score', 0)}%", delta=None)
    with col3:
        st.metric("Days Completed", f"{stats.get('completed_days', 0)}/7", delta=None)
    with col4:
        completion_rate = round((stats.get('completed_days', 0) / 7) * 100)
        st.metric("Completion", f"{completion_rate}%", delta=None)
    
    st.divider()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💻 Coded Days", stats.get('coded_days', 0))
    with col2:
        st.metric("🥗 Clean Days", stats.get('clean_days', 0))
    with col3:
        st.metric("🏋️ Workout Days", stats.get('workout_days', 0))
    with col4:
        st.metric("💪 Total Pushups", stats.get('total_pushups', 0))
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("📚 Study Hours", f"{stats.get('total_study', 0)}")
    with col2:
        st.metric("💧 Water Liters", f"{stats.get('total_water', 0)}")

# --- STREAK INFORMATION ---
if show_streaks:
    st.divider()
    st.markdown("""
    <div style='text-align: center; margin: 20px 0;'>
        <h2 style='color: #f59e0b; text-shadow: 0 0 20px rgba(245, 158, 11, 0.6);'>🔥 CURRENT STREAKS</h2>
    </div>
    """, unsafe_allow_html=True)
    
    streak_cols = st.columns(3)
    
    with streak_cols[0]:
        current, longest = get_streak_data('coded_today')
        st.metric("💻 Coding Streak", f"{current} days", f"Best: {longest}")
    
    with streak_cols[1]:
        current, longest = get_streak_data('no_junk_food')
        st.metric("🥗 Clean Eating", f"{current} days", f"Best: {longest}")
    
    with streak_cols[2]:
        current, longest = get_streak_data('workout_done')
        st.metric("🏋️ Workout Streak", f"{current} days", f"Best: {longest}")

# --- MONTHLY VIEW ---
if show_history:
    st.divider()
    st.markdown("""
    <div style='text-align: center; margin: 20px 0;'>
        <h2 style='color: #d946ef; text-shadow: 0 0 20px rgba(217, 70, 239, 0.6);'>📈 JOURNEY PROGRESS</h2>
    </div>
    """, unsafe_allow_html=True)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        df_all = pd.read_sql_query(
            "SELECT log_date, victory_score FROM daily_log WHERE log_date >= date('now', '-30 days') ORDER BY log_date",
            conn
        )
        conn.close()
        
        if not df_all.empty:
            df_all['log_date'] = pd.to_datetime(df_all['log_date'])
            df_all.set_index('log_date', inplace=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.line_chart(df_all['victory_score'], height=300, color="#4CAF50")
            with col2:
                st.bar_chart(df_all['victory_score'], height=300, color="#FF5252")
        else:
            st.info("No historical data available yet. Keep tracking!")
    except Exception as e:
        st.error(f"Error loading history: {e}")

# --- EXECUTION SCORE GRAPH ---
st.divider()
st.markdown("""
<div style='text-align: center; margin: 20px 0;'>
    <h2 style='color: #d946ef; text-shadow: 0 0 20px rgba(217, 70, 239, 0.6);'>⚡ POWER LEVEL CHART</h2>
</div>
""", unsafe_allow_html=True)

if not edited_df.empty:
    try:
        plot_data = edited_df.copy()
        
        # Calculate visual completion status
        plot_data['Status'] = plot_data['victory_score'].apply(
            lambda x: "✅ Complete" if x == 100 else ("⚠️ Partial" if x > 0 else "❌ Empty")
        )
        
        plot_data['Score Achieved'] = plot_data['victory_score']
        plot_data['Score Missed'] = 100 - plot_data['victory_score']
        
        chart_data = plot_data.set_index('Day')[['Score Achieved', 'Score Missed']]
        
        st.line_chart(chart_data, color=["#4CAF50", "#FF5252"], height=300)
    except Exception as e:
        st.error(f"Error rendering chart: {e}")