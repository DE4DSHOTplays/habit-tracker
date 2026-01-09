import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURATION ---
SCORE_CONFIG = {
    'coded_today': 30,
    'no_junk_food': 20,
    'workout_done': 10,
    'pushups_max': 30,
    'study_hours_max': 10,
}

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

# --- BACKEND FUNCTIONS ---

def get_current_week_dates(offset_weeks=0):
    """Returns a list of dates for a week (Sunday to Saturday)."""
    today = date.today()
    target_date = today - timedelta(weeks=-offset_weeks)
    days_to_subtract = (target_date.weekday() + 1) % 7
    start_sunday = target_date - timedelta(days=days_to_subtract)
    
    week_dates = []
    for i in range(7):
        week_dates.append(start_sunday + timedelta(days=i))
    return week_dates, start_sunday

@st.cache_data(ttl=60)
def get_display_data(offset_weeks=0):
    """Get data for the specified week from Google Sheets."""
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    try:
        df_db = conn.read(worksheet="Sheet1")
    except:
        df_db = pd.DataFrame()

    week_dates, start_sunday = get_current_week_dates(offset_weeks)
    str_dates = [d.isoformat() for d in week_dates]
    df_week = pd.DataFrame({'log_date': str_dates})
    
    if not df_db.empty:
        df_db['log_date'] = df_db['log_date'].astype(str)
        df_final = pd.merge(df_week, df_db, on='log_date', how='left')
    else:
        df_final = df_week

    required_cols = {
        'coded_today': False, 'no_junk_food': False, 'workout_done': False,
        'pushups': 0, 'study_hours': 0.0, 'water_liters': 0.0, 'victory_score': 0, 'notes': ''
    }
    for col, default_val in required_cols.items():
        if col not in df_final.columns:
            df_final[col] = default_val

    # Fill NaNs
    df_final['pushups'] = df_final['pushups'].fillna(0)
    df_final['study_hours'] = df_final['study_hours'].fillna(0.0)
    df_final['water_liters'] = df_final['water_liters'].fillna(0.0)
    df_final['victory_score'] = df_final['victory_score'].fillna(0)
    df_final['notes'] = df_final['notes'].fillna("")
    
    bool_cols = ['coded_today', 'no_junk_food', 'workout_done']
    for col in bool_cols:
        df_final[col] = df_final[col].fillna(False).astype(bool)

    # Formatting
    df_final['Day'] = df_final['log_date'].apply(
        lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%d %b %a").upper()
    )
    
    cols = ['Day', 'log_date'] + [c for c in df_final.columns if c not in ['Day', 'log_date']]
    return df_final[cols], start_sunday

def get_all_history_df():
    """Fetch all historical data for charts."""
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df = conn.read(worksheet="Sheet1")
        df['log_date'] = pd.to_datetime(df['log_date'])
        return df.sort_values('log_date')
    except:
        return pd.DataFrame()

def calculate_current_streak(df, column_name):
    """Calculate the current active streak for a specific habit."""
    if df.empty or column_name not in df.columns:
        return 0
    
    df = df.sort_values('log_date', ascending=False)
    today = pd.Timestamp(date.today())
    
    streak = 0
    is_done = df[column_name].astype(bool).tolist()
    dates = df['log_date'].tolist()
    
    if not dates:
        return 0
        
    days_since_last_log = (today - dates[0]).days
    if days_since_last_log > 1:
        return 0
        
    for i, done in enumerate(is_done):
        if i > 0:
            gap = (dates[i-1] - dates[i]).days
            if gap > 1: break
        
        if done:
            streak += 1
        else:
            if (today - dates[i]).days > 0: 
                break
    return streak

def save_grid_changes(edited_df):
    """Save grid changes to Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        try:
            full_history_df = conn.read(worksheet="Sheet1")
            full_history_df['log_date'] = full_history_df['log_date'].astype(str)
        except:
            full_history_df = pd.DataFrame()

        save_df = edited_df.copy()
        if 'Day' in save_df.columns:
            save_df = save_df.drop(columns=['Day'])
            
        for index, row in save_df.iterrows():
            score = 0
            if row['coded_today']: score += SCORE_CONFIG['coded_today']
            if row['no_junk_food']: score += SCORE_CONFIG['no_junk_food']
            if row['workout_done']: score += SCORE_CONFIG['workout_done']
            score += min(row['pushups'] * 1, SCORE_CONFIG['pushups_max'])
            score += min(row['study_hours'] * 5, SCORE_CONFIG['study_hours_max'])
            save_df.at[index, 'victory_score'] = min(score, 100)

        if not full_history_df.empty:
            dates_being_updated = save_df['log_date'].tolist()
            history_kept = full_history_df[~full_history_df['log_date'].isin(dates_being_updated)]
            final_df = pd.concat([history_kept, save_df], ignore_index=True)
        else:
            final_df = save_df

        final_df = final_df.sort_values('log_date')
        conn.update(worksheet="Sheet1", data=final_df)
        
        st.success("✅ Synced with Google Sheets!")
        return True
    except Exception as e:
        st.error(f"Google Sheets Sync Error: {e}")
        return False

def get_completion_stats(df):
    try:
        stats = {
            'total_score': int(df['victory_score'].sum()),
            'avg_score': round(df['victory_score'].mean(), 1),
            'completed_days': len(df[df['victory_score'] > 0]),
        }
        return stats
    except:
        return {}

def export_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# --- FRONTEND ---
st.set_page_config(page_title="Vikrant's Tracker", page_icon="💪", layout="wide")

st.markdown("""
<style>
    .main { background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%); }
    [data-testid="stAppViewContainer"] { background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%); }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f1028 0%, #1a1a3e 100%); border-right: 2px solid #7c3aed; }
    h1, h2, h3, h4, h5, h6 { color: #e0e0ff; text-shadow: 0 0 20px rgba(124, 58, 237, 0.5); }
    p, label, span { color: #c0c0ff; }
    [data-testid="metric-container"] { background: linear-gradient(135deg, #1a0033 0%, #2d0052 100%); border: 1px solid #7c3aed; border-radius: 12px; }
    button { background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%) !important; color: white !important; }
    [data-testid="dataframe"] { background: #0f1028 !important; border: 1px solid #7c3aed !important; }
</style>
""", unsafe_allow_html=True)

st.title("📅 Weekly Habit Sheet")

with st.sidebar:
    st.markdown("<h3 style='color: #d946ef;'>⚔️ MISSION CONTROL</h3>", unsafe_allow_html=True)
    if 'week_offset' not in st.session_state:
        st.session_state.week_offset = 0

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Previous", use_container_width=True):
            st.session_state.week_offset -= 1
            st.cache_data.clear()
            st.rerun()
    with col2:
        if st.button("Current →", use_container_width=True):
            st.session_state.week_offset = 0
            st.cache_data.clear()
            st.rerun()

    if st.button("Next →", use_container_width=True):
        st.session_state.week_offset += 1
        st.cache_data.clear()
        st.rerun()

    week_offset = st.session_state.week_offset

# Load Data
df, week_start = get_display_data(week_offset)
week_label = week_start.strftime("%d %b %Y")
st.markdown(f"### 📅 Week of {week_label}")

# Grid
column_config = {
    "Day": st.column_config.TextColumn("Day", disabled=True),
    "log_date": None,
    "coded_today": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['coded_today']} Coded?", default=False),
    "no_junk_food": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['no_junk_food']} No Junk", default=False),
    "workout_done": st.column_config.CheckboxColumn(f"{EMOJI_CONFIG['workout_done']} Workout", default=False),
    "pushups": st.column_config.NumberColumn(f"{EMOJI_CONFIG['pushups']} Pushups", format="%d"),
    "study_hours": st.column_config.NumberColumn(f"{EMOJI_CONFIG['study_hours']} Study", format="%.1f"),
    "water_liters": st.column_config.NumberColumn(f"{EMOJI_CONFIG['water_liters']} Water", format="%.1f"),
    "notes": st.column_config.TextColumn(f"{EMOJI_CONFIG['notes']} Notes", default=""),
    "victory_score": st.column_config.ProgressColumn(f"{EMOJI_CONFIG['score']} Score", format="%d%%", min_value=0, max_value=100),
}

with st.form("weekly_form"):
    edited_df = st.data_editor(df, column_config=column_config, num_rows="fixed", hide_index=True, use_container_width=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        save_clicked = st.form_submit_button("💾 Save Changes", use_container_width=True)
    with col2:
        export_clicked = st.form_submit_button("📥 Export CSV", use_container_width=True)
    with col3:
        reset_clicked = st.form_submit_button("🔄 Refresh", use_container_width=True)
    
    if save_clicked:
        if save_grid_changes(edited_df):
            st.session_state.week_offset = 0
            st.cache_data.clear()
            st.rerun()
    
    if export_clicked:
        st.download_button("Download CSV", export_to_csv(edited_df), f"habit_tracker_{week_start}.csv", "text/csv")
        
    if reset_clicked:
        st.cache_data.clear()
        st.rerun()

# Stats
st.divider()
if not edited_df.empty:
    stats = get_completion_stats(edited_df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Score", stats.get('total_score', 0))
    c2.metric("Avg Score", f"{stats.get('avg_score', 0)}%")
    c3.metric("Days Active", f"{stats.get('completed_days', 0)}/7")

# Charts & Streaks
st.divider()
history_df = get_all_history_df()

if not history_df.empty:
    col_graph, col_streak = st.columns([2, 1])

    with col_graph:
        st.subheader("📈 Victory Score History")
        chart_data = history_df[history_df['log_date'] <= pd.Timestamp(date.today())]
        if not chart_data.empty:
            chart_data = chart_data.set_index('log_date')
            st.line_chart(chart_data['victory_score'], color="#d946ef", height=300)

    with col_streak:
        st.subheader("🔥 Current Streaks")
        s_code = calculate_current_streak(history_df, 'coded_today')
        s_junk = calculate_current_streak(history_df, 'no_junk_food')
        s_work = calculate_current_streak(history_df, 'workout_done')
        
        st.info(f"💻 Coding Streak: **{s_code} days**")
        st.info(f"🥗 Clean Eating: **{s_junk} days**")
        st.info(f"🏋️ Workout Streak: **{s_work} days**")
else:
    st.info("Start logging data to see your progress graph and streaks!")
