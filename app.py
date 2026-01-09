import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURATION ---
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

# --- BACKEND FUNCTIONS ---

def get_current_week_dates(offset_weeks=0):
    """Returns a list of dates for a week (Sunday to Saturday), with optional week offset."""
    today = date.today()
    # Adjust to the target week
    target_date = today - timedelta(weeks=-offset_weeks)  # Fixed sign for intuitive navigation
    
    # Find the Sunday of that week
    # weekday(): Mon=0, Sun=6. If today is Sun(6), we subtract 6 days? No, standard is usually Sun=0.
    # Python date.weekday() returns Mon=0, Sun=6.
    # To make Sunday the start: 
    days_to_subtract = (target_date.weekday() + 1) % 7
    start_sunday = target_date - timedelta(days=days_to_subtract)
    
    week_dates = []
    for i in range(7):
        week_dates.append(start_sunday + timedelta(days=i))
    return week_dates, start_sunday

@st.cache_data(ttl=60)
def get_display_data(offset_weeks=0):
    """Get data for the specified week from Google Sheets with caching."""
    # 1. Connect to Google Sheets
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 2. Read data (handle empty sheet case)
    try:
        df_db = conn.read(worksheet="Sheet1")
    except:
        df_db = pd.DataFrame()

    # 3. Get standard week dates (Sun -> Sat)
    week_dates, start_sunday = get_current_week_dates(offset_weeks)
    str_dates = [d.isoformat() for d in week_dates]
    
    # 4. Create Master DataFrame for the requested week
    df_week = pd.DataFrame({'log_date': str_dates})
    
    if not df_db.empty:
        # Ensure log_date is string for merging
        df_db['log_date'] = df_db['log_date'].astype(str)
        # Merge DB data into the week structure
        df_final = pd.merge(df_week, df_db, on='log_date', how='left')
    else:
        df_final = df_week

    # 5. Defaults for missing data
    required_cols = {
        'coded_today': False, 
        'no_junk_food': False, 
        'workout_done': False,
        'pushups': 0, 
        'study_hours': 0.0, 
        'water_liters': 0.0, 
        'victory_score': 0, 
        'notes': ''
    }
    
    for col, default_val in required_cols.items():
        if col not in df_final.columns:
            df_final[col] = default_val

    # Fill NaNs with defaults (important for new days)
    # We must handle types carefully. 
    df_final['pushups'] = df_final['pushups'].fillna(0)
    df_final['study_hours'] = df_final['study_hours'].fillna(0.0)
    df_final['water_liters'] = df_final['water_liters'].fillna(0.0)
    df_final['victory_score'] = df_final['victory_score'].fillna(0)
    df_final['notes'] = df_final['notes'].fillna("")
    
    # 6. Fix Boolean Types (Streamlit needs actual bools for checkboxes)
    bool_cols = ['coded_today', 'no_junk_food', 'workout_done']
    for col in bool_cols:
        df_final[col] = df_final[col].fillna(False).astype(bool)

    # 7. FORMATTING FOR DISPLAY
    # Add 'Day' column like "09 JAN FRI"
    df_final['Day'] = df_final['log_date'].apply(
        lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%d %b %a").upper()
    )
    
    # Move 'Day' to the front, keep 'log_date' for logic
    cols = ['Day', 'log_date'] + [c for c in df_final.columns if c not in ['Day', 'log_date']]
    return df_final[cols], start_sunday

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
    """Save grid changes to Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # 1. Read existing full history to avoid overwriting other weeks
        try:
            full_history_df = conn.read(worksheet="Sheet1")
            full_history_df['log_date'] = full_history_df['log_date'].astype(str)
        except:
            full_history_df = pd.DataFrame()

        # 2. Clean the edited data
        save_df = edited_df.copy()
        
        # Remove the display column 'Day'
        if 'Day' in save_df.columns:
            save_df = save_df.drop(columns=['Day'])
            
        # Recalculate scores for the edited rows
        for index, row in save_df.iterrows():
            # Future Date Check (Optional: You can uncomment to lock future dates)
            # if row['log_date'] > date.today().isoformat(): continue

            score = 0
            if row['coded_today']: score += SCORE_CONFIG['coded_today']
            if row['no_junk_food']: score += SCORE_CONFIG['no_junk_food']
            if row['workout_done']: score += SCORE_CONFIG['workout_done']
            score += min(row['pushups'] * 1, SCORE_CONFIG['pushups_max'])
            score += min(row['study_hours'] * 5, SCORE_CONFIG['study_hours_max'])
            save_df.at[index, 'victory_score'] = min(score, 100)

        # 3. Merge Strategy
        if not full_history_df.empty:
            # Get the list of dates we are currently updating
            dates_being_updated = save_df['log_date'].tolist()
            
            # Keep all history rows that are NOT in the list of dates we are updating
            history_kept = full_history_df[~full_history_df['log_date'].isin(dates_being_updated)]
            
            # Combine kept history with the new updates
            final_df = pd.concat([history_kept, save_df], ignore_index=True)
        else:
            final_df = save_df

        # 4. Sort and Save
        final_df = final_df.sort_values('log_date')
        conn.update(worksheet="Sheet1", data=final_df)
        
        st.success("✅ Synced with Google Sheets!")
        return True
        
    except Exception as e:
        st.error(f"Google Sheets Sync Error: {e}")
        return False

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
        return {}

def export_to_csv(df):
    """Generate CSV export data."""
    try:
        return df.to_csv(index=False).encode('utf-8')
    except Exception as e:
        st.error(f"Export error: {e}")
        return None

# --- FRONTEND ---
st.set_page_config(page_title="Vikrant's Supreme Tracker", page_icon="💪", layout="wide", initial_sidebar_state="expanded")

# --- SOLO LEVELING THEME CSS ---
st.markdown("""
<style>
    .main { background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%); }
    [data-testid="stAppViewContainer"] { background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%); }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f1028 0%, #1a1a3e 100%); border-right: 2px solid #7c3aed; }
    h1, h2, h3, h4, h5, h6 { color: #e0e0ff; text-shadow: 0 0 20px rgba(124, 58, 237, 0.5); font-family: 'Arial', sans-serif; font-weight: 700; }
    p, label, span { color: #c0c0ff; }
    [data-testid="metric-container"] { background: linear-gradient(135deg, #1a0033 0%, #2d0052 100%); border: 1px solid #7c3aed; border-radius: 12px; padding: 20px; box-shadow: 0 0 20px rgba(124, 58, 237, 0.3); }
    button { background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%) !important; color: #ffffff !important; border: 1px solid #d8b4fe !important; border-radius: 8px !important; }
    input, textarea, select { background: #1a0033 !important; color: #e0e0ff !important; border: 1px solid #7c3aed !important; }
    [data-testid="dataframe"] { background: #0f1028 !important; border: 1px solid #7c3aed !important; }
    hr { border-top: 2px solid #7c3aed; }
</style>
""", unsafe_allow_html=True)

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
    st.markdown("<h3 style='color: #d946ef;'>⚔️ MISSION CONTROL</h3>", unsafe_allow_html=True)
    
    # Initialize session state for week offset
    if 'week_offset' not in st.session_state:
        st.session_state.week_offset = 0

    st.subheader("🗓️ Navigate Weeks")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Previous", use_container_width=True):
            st.session_state.week_offset -= 1
            st.cache_data.clear() # Clear cache to fetch new week data
            st.rerun()
            
    with col2:
        if st.button("Current →", use_container_width=True):
            st.session_state.week_offset = 0
            st.cache_data.clear()
            st.rerun()
            
    # Next week button (Future)
    if st.button("Next →", use_container_width=True):
        st.session_state.week_offset += 1
        st.cache_data.clear()
        st.rerun()

    week_offset = st.session_state.week_offset

# 1. Load Data
df, week_start = get_display_data(week_offset)
week_label = week_start.strftime("%d %b %Y")

st.markdown(f"### 📅 Week of {week_label}")

# 2. Grid Config
column_config = {
    "Day": st.column_config.TextColumn("Day", disabled=True),
    "log_date": None, # Hidden
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
        reset_clicked = st.form_submit_button("🔄 Refresh", use_container_width=True)
    
    # --- SAVE LOGIC (FIXED) ---
    if save_clicked:
        # No extra checkbox here!
        if save_grid_changes(edited_df):
            st.session_state.week_offset = 0
            st.cache_data.clear()
            st.rerun()
    
    if export_clicked:
        csv_data = export_to_csv(edited_df)
        if csv_data:
            st.download_button(
                label="Click to Download CSV",
                data=csv_data,
                file_name=f"habit_tracker_{week_start.isoformat()}.csv",
                mime="text/csv"
            )
    
    if reset_clicked:
        st.cache_data.clear()
        st.rerun()

# --- WEEKLY STATISTICS ---
st.divider()
st.markdown("<h2 style='text-align: center; color: #d946ef;'>📊 WEEKLY PERFORMANCE</h2>", unsafe_allow_html=True)

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
