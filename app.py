from flask import Flask, render_template, request, redirect, url_for, session, flash
import urllib.request
import urllib.parse
import urllib.error
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import requests
import warnings
import os

warnings.filterwarnings('ignore')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

PORT = int(os.environ.get('PORT', 5000))

def get_forecast_data(latitude, longitude, custom_date=None):
    """Generate forecast data for given coordinates"""
    parameters = 'T2M,T2M_MIN,T2M_MAX,RH2M,WS2M,PRECTOTCORR'
    community = 'AG'

    today = custom_date if custom_date else datetime.now().date()
    wek = 7
    start_today = today

    historical_dfs = []
    years_back = [5, 6, 7]
    params_list = ['T2M', 'T2M_MIN', 'T2M_MAX', 'RH2M', 'WS2M', 'PRECTOTCORR']

    for y in years_back:
        hist_year = start_today.year - y
        hist_start = date(hist_year, start_today.month, start_today.day)
        hist_end = hist_start + timedelta(days=wek - 1)
        start_str = hist_start.strftime('%Y%m%d')
        end_str = hist_end.strftime('%Y%m%d')
        hist_df = fetch_nasa_data(latitude, longitude, start_str, end_str, parameters, community)
        if not hist_df.empty:
            mask = hist_df[params_list].ne(-999.0).all(axis=1)
            hist_df_filtered = hist_df[mask].sort_values('date')
            if len(hist_df_filtered) == wek:
                historical_dfs.append(hist_df_filtered[params_list].values)

    extended_years_data = []
    for i, year_array in enumerate(historical_dfs):
        year_df = pd.DataFrame(year_array, columns=params_list)
        year_sunrise = []
        year_sunset = []
        hist_year = start_today.year - years_back[i]
        hist_dates = pd.date_range(start=date(hist_year, start_today.month, start_today.day), periods=wek, freq='D')
        for h_date in hist_dates:
            sr, ss = get_sunrise_sunset(latitude, longitude, h_date.strftime('%Y-%m-%d'))
            year_sunrise.append(sr or "N/A")
            year_sunset.append(ss or "N/A")
        year_df['Sunrise'] = year_sunrise
        year_df['Sunset'] = year_sunset
        year_data_rounded = []
        for row in year_df.values:
            rounded_row = [round(val, 1) if isinstance(val, (int, float)) else val for val in row]
            year_data_rounded.append(rounded_row)
        extended_years_data.append(year_data_rounded)

    while len(extended_years_data) < 3:
        empty_year = [['N/A'] * 8 for _ in range(7)]
        extended_years_data.append(empty_year)

    return extended_years_data

@app.route("/")
def home():
    # Get location from session or auto-detect
    if 'city' in session and 'latitude' in session and 'longitude' in session:
        city = session['city']
        latitude = session['latitude']
        longitude = session['longitude']
    else:
        latitude, longitude, city = get_user_location_by_ip()
        # Validate coordinates before storing in session
        if latitude is None or longitude is None:
            # Fallback to default location with known coordinates
            latitude, longitude = get_coordinates("Uralsk")
            city = "Uralsk"
        session['city'] = city
        session['latitude'] = latitude
        session['longitude'] = longitude

    # Get current time and date
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    
    # Check if custom date is set in session
    if 'custom_date' in session:
        custom_date = datetime.strptime(session['custom_date'], '%Y-%m-%d').date()
        current_date = custom_date.strftime('%B %d, %Y')
    else:
        current_date = now.strftime('%B %d, %Y')
        custom_date = None

    # Generate forecast data
    forecast_data = get_forecast_data(latitude, longitude, custom_date)
    
    # Prepare chart data for 7-day predictions
    chart_labels = []
    avg_temps = []
    min_temps = []
    max_temps = []
    
    base_date = custom_date if custom_date else datetime.now().date()
    
    # Extract data from first historical year (index 0) for all 7 days
    if len(forecast_data) > 0 and len(forecast_data[0]) >= 7:
        for day_idx in range(7):
            day_date = base_date + timedelta(days=day_idx)
            chart_labels.append(day_date.strftime('%b %d'))
            
            day_data = forecast_data[0][day_idx]
            avg_temps.append(day_data[0] if isinstance(day_data[0], (int, float)) else 0)
            min_temps.append(day_data[1] if isinstance(day_data[1], (int, float)) else 0)
            max_temps.append(day_data[2] if isinstance(day_data[2], (int, float)) else 0)

    return render_template("index.html",
                           forecast_data=forecast_data,
                           current_time=current_time,
                           current_date=current_date,
                           city=city,
                           chart_labels=json.dumps(chart_labels),
                           avg_temps=json.dumps(avg_temps),
                           min_temps=json.dumps(min_temps),
                           max_temps=json.dumps(max_temps))

@app.route("/update_location", methods=['POST'])
def update_location():
    city_name = request.form.get('city')
    if city_name:
        lat, lon = get_coordinates(city_name)
        if lat is not None and lon is not None:
            session['city'] = city_name
            session['latitude'] = lat
            session['longitude'] = lon
        else:
            # Keep existing location if geocoding fails
            pass
    return redirect(url_for('home'))

@app.route("/update_date", methods=['POST'])
def update_date():
    date_str = request.form.get('date')
    if date_str:
        session['custom_date'] = date_str
    return redirect(url_for('home'))


def get_coordinates(city):
    """Автоматическое определение широты/долготы по названию города через Nominatim API"""
    encoded_city = urllib.parse.quote(city)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&format=json&limit=1"
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        if data:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return lat, lon
    except Exception as e:
        pass
    return None, None  # Fallback


def get_user_location_by_ip():
    """Автоматическое определение местоположения по IP (публичный IP + гео)"""
    try:
        # Получить публичный IP пользователя
        ip_response = requests.get('https://api.ipify.org?format=json')
        ip_data = ip_response.json()
        user_ip = ip_data['ip']

        # Получить гео по IP (ipapi.co — бесплатно, lat/lon/city/country)
        geo_response = requests.get(f'https://ipapi.co/{user_ip}/json/')
        geo_data = geo_response.json()

        city = geo_data.get('city', None)
        if city == 'Unknown' or not city:
            city = "Uralsk"  # Fallback для Казахстана (по IP 93.157.178.87 — Tele2 Kazakhstan)
        lat = geo_data.get('latitude')
        lon = geo_data.get('longitude')

        if lat and lon:
            return float(lat), float(lon), city  # Успех
        else:
            # Fallback: Nominatim по городу
            lat, lon = get_coordinates(city)
            return lat, lon, city
    except Exception as e:
        lat, lon = get_coordinates("Uralsk")
        return lat, lon, "Uralsk"


def get_sunrise_sunset(lat, lon, date_str):
    """Получение времени восхода/захода солнца для даты через Sunrise-Sunset API (UTC+5 для Uralsk)"""
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={date_str}&formatted=0"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
        if data['status'] == 'OK':
            # Извлечение времени из ISO строки (после T, до +)
            sunrise_utc = data['results']['sunrise'].split('T')[1].split(
                '+')[0][:5]  # HH:MM
            sunset_utc = data['results']['sunset'].split('T')[1].split(
                '+')[0][:5]  # HH:MM

            # Корректировка на UTC+5 (Uralsk timezone; для других — подкорректируй)
            sunrise_h, sunrise_m = map(int, sunrise_utc.split(':'))
            sunset_h, sunset_m = map(int, sunset_utc.split(':'))

            # Добавление 5 часов (модуль 24)
            sunrise_local_h = (sunrise_h + 5) % 24
            sunset_local_h = (sunset_h + 5) % 24

            sunrise = f"{sunrise_local_h:02d}:{sunrise_m:02d}"
            sunset = f"{sunset_local_h:02d}:{sunset_m:02d}"

            return sunrise, sunset
    except Exception as e:
        pass
    return None, None


def fetch_nasa_data(latitude, longitude, start, end, parameters, community):
    """Запрос данных за один период из NASA API"""
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters={parameters}&community={community}&longitude={longitude}&latitude={latitude}&start={start}&end={end}&format=JSON"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
        properties = data['properties']['parameter']
        param_keys = list(properties.keys())
        dates = list(properties[param_keys[0]].keys())
        df_data = {}
        for param in param_keys:
            df_data[param] = [properties[param][date] for date in dates]
        df = pd.DataFrame({'date': pd.to_datetime(dates), **df_data})
        return df
    except urllib.error.HTTPError as e:
        if e.code == 422:
            error_body = e.read().decode()
            pass
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=PORT))
