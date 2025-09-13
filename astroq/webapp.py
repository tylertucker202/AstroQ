"""
Web application module for AstroQ.
"""

# Standard library imports
import base64
import os
import pickle
import threading
from configparser import ConfigParser
from io import BytesIO

# Third-party imports
import imageio.v3 as iio
import numpy as np
import pandas as pd
import plotly.io as pio
from flask import Flask, render_template, request, abort, send_from_directory, jsonify
from socket import gethostname

# Local imports
import astroq.nplan as nplan
import astroq.plot as pl
from itertools import product
import astroq.splan as splan
from astropy.time import Time, TimeDelta
import pdb

running_on_keck_machines = False

app = Flask(__name__, template_folder="../templates")

# Global variables to store loaded data
data_astroq = None
semester_planner = None
night_planner = None
uptree_path = '.'  # TODO make config


def load_data_for_path(semester_code, date, band, page=None):
    """Load data for a specific semester_code/date/band combination"""
    global data_astroq, semester_planner, night_planner

    # Construct the workdir path based on URL parameters
    workdir = os.path.join(uptree_path, semester_code, date, band, "outputs")
    if not os.path.exists(workdir):
        return False, f"Directory not found: {workdir}"

    if page == "nightplan":
        night_planner_pkl = os.path.join(workdir, 'night_planner.pkl')
        # Load night planner (optional)
        try:
            with open(night_planner_pkl, 'rb') as f:
                night_planner = pickle.load(f)
        except:
            night_planner = None
            return False, f"Error loading night planner from {night_planner_pkl}"
        return True, "Data loaded successfully"

    if page == "admin" or page == 'star':
        semester_planner_pkl = os.path.join(workdir, 'semester_planner.pkl')
        data_astroq_pkl = os.path.join(workdir, 'data_astroq.pkl')
        # Load semester planner
        try:
            with open(semester_planner_pkl, 'rb') as f:
                semester_planner = pickle.load(f)
            if not os.path.exists(data_astroq_pkl):
                print(f"data_astroq.pkl not found in {workdir}")
                data_astroq = pl.process_stars(
                    semester_planner)  # writing data_astroq.pkl
                with open(data_astroq_pkl, 'wb') as f:
                    pickle.dump(data_astroq, f)
            else:
                with open(data_astroq_pkl, 'rb') as f:
                    data_astroq = pickle.load(f)
        except Exception as e:
            semester_planner = None
            data_astroq = None
            return False, f"Error loading semester planner: {str(e)}"
        except Exception as e:
            semester_planner = None
            return False, f"Error loading semester planner: {str(e)}"
        return True, "Data loaded successfully"


# New homepage with navigation instructions
@app.route("/", methods=["GET"])
def index():
    navigation_text = """
    To navigate, append to the URL in the following way: 
    url/{semester_code}/{date}/{band}/{page} 
    
    where:
    - semester_code is 2025B (for example)
    - date is in format YYYY-MM-DD
    - band is either band1 or band3
    - page is one of the following: admin, star/{starname}, nightplan, or {program_code}
    
    Examples:
    - /2025B/2025-01-15/band1/admin
    - /2025B/2025-01-15/band1/star/HD4614
    - /2025B/2025-01-15/band3/nightplan
    - /2025B/2025-01-15/band1/2025B_N001 
    """
    return render_template("homepage.html", navigation_text=navigation_text)


def get_ladder_data():
    data_tts = night_planner.solution if night_planner is not None else None
    data = pd.DataFrame.from_dict(
        data_tts[0].plotly).to_dict(orient='records')
    if data_tts is None:
        raise ValueError("Error: No night planner solution data available")
    ladder_data = data
    return ladder_data


def get_slew_animation_data():
    data_tts = night_planner.solution if night_planner is not None else None
    model = data_tts[0]
    tstart, tend = model.nightstarts.jd, model.nightends.jd
    stars = model.stars
    targets = []
    animationStep = 120  # seconds
    times = np.arange(tstart, tend, TimeDelta(animationStep, format='sec').jd)
    tjd = Time(times, format='jd')
    list_targets = []
    for n in range(len(model.schedule['Starname'])):
        for s in stars:
            if s.name == model.schedule['Starname'][n]:
                list_targets.append(s.target)
    for star in stars:
        tgt = star.__dict__
        del tgt['target']
        targets.append(tgt)

    # Compute alt/az of each target at each time
    AZ = model.observatory.observer.altaz(tjd, list_targets, grid_times_targets=True)

    # Telescope slew path
    stamps = [0] * len(tjd)

    slewPath = pl.createTelSlewPath(stamps, model.schedule['Time'], list_targets)
    AZ1 = model.observatory.observer.altaz( tjd, slewPath, grid_times_targets=False)

    # rows are times, columns are targets
    alt = np.round(AZ.az.rad, 2).T.tolist()
    az = (90 - np.round(AZ.alt.deg, 2)).T.tolist()
    tel_az = np.round(AZ1.az.rad, 2).tolist()
    tel_zen = 90 - np.round(AZ1.alt.deg, 2).tolist()

    slew_animation_data = {
        'targets': targets,
        'tel_az': tel_az,  # path of telescope azimuth
        'tel_zen': tel_zen,
        'alt': alt,  # altitudes of all targets
        'az': az,
        'times': tjd.isot.tolist()
    }
    return slew_animation_data

# Dynamic data for all pages

def get_cof_data(all_stars):
    lines = []
    for star in all_stars:
        line = dict(
            dates=star.dates.astype(str).tolist(),
            cumulative_observe_pct=star.cume_observe_pct.astype(float).tolist(),
            name=star.starname,
            total_observations_requested=star.total_observations_requested
        )
        lines.append(line)
    return lines

def get_cof_data_for_starname(starname):

    program_dict = data_astroq[0]

    for program in program_dict.values():
        for star_obj in program:
            true_starname = star_obj.starname
            object_compare_starname = true_starname.lower().replace(' ', '')
            if object_compare_starname != starname:
                continue
            # Get request frame table for this specific star
            request_df = pl.get_request_frame(semester_planner, [star_obj])
            starinfo = request_df.to_dict(orient='records')
    
    if starinfo is None:
        raise ValueError(f"Error, star {starname} not found in programs {list(program_dict.keys())}")
    lines = get_cof_data([star_obj])
    cof_data = {
        'starinfo': starinfo,
        'lines': lines
    }
    return cof_data, star_obj

def get_football_data(program_stars):
    starnames = [star.starname for star in program_stars]
    programs = [star.program for star in program_stars]
    ras = [star.ra for star in program_stars]
    decs = [star.dec for star in program_stars]
    # Choose color based on flag
    programs = pd.DataFrame({"starname":starnames, "program_code":programs, "ra":ras, "dec":decs}).to_dict(orient='records')
    NIGHTS_grid, RA_grid, DEC_grid = pl.get_grid_data(semester_planner)

    football_data = {
        'programs': programs,
        'nights_grid': NIGHTS_grid.tolist(),
        'ra_grid': RA_grid.tolist(),
        'dec_grid': DEC_grid.tolist()
    }
    return football_data

def get_tau_inter_line_data(stars):
    request_tau_inter = []
    onsky_tau_inter = []
    starnames = []
    programs = []
    for starobj in stars:
        onsky_diffs = list(np.diff(np.where(np.diff(starobj.cume_observe) > 0)[0]))
        onsky_tau_inter.extend(onsky_diffs)
        request_tau_inter.extend([starobj.tau_inter] * len(onsky_diffs))
        starnames.extend([starobj.starname] * len(onsky_diffs))
        programs.extend([starobj.program] * len(onsky_diffs))

    all_onsky_tau_inters = np.array(onsky_tau_inter)

    tau_inter_line_data = {
        'programs': programs,
        'starnames': starnames,
        'onsky_tau_inter': all_onsky_tau_inters.tolist(),
        'request_tau_inter': request_tau_inter
    }
    return tau_inter_line_data


@app.route("/data/<semester_code>/<date>/<band>/<page>")
def dynamic_data(semester_code, date, band, page=None):
    """Handle all dynamic routes based on URL parameters"""
    # Validate parameters
    if band not in ['band1', 'band3']:  # TODO put in config file
        abort(400, description="Band must be 'band1' or 'band3'")

    program_code = request.args.get('program_code')
    starname = request.args.get('starname')

    # Load data for this path
    if program_code is not None:
        # to get semester_planner and data_astroq
        success, message = load_data_for_path(
            semester_code, date, band, 'admin')
    else:
        success, message = load_data_for_path(semester_code, date, band, page)
    if not success:
        return f"Error: {message}", 404

    # Route to appropriate page based on parameters
    if starname is not None:

        cof_data, star_obj = get_cof_data_for_starname(starname)

        request_df = pl.get_request_frame(semester_planner, [star_obj])
        request_data = request_df.to_dict(orient='records')
        birdseye_data = {
            'starmap': star_obj.starmap.tolist(),
            'dates': semester_planner.add_dates_array.tolist(), 
        }

        tau_inter_line_data = get_tau_inter_line_data([star_obj])
        football_data = get_football_data([star_obj])

        data = {
            'request_data': request_data,
            'cof': cof_data,
            'birdseye': birdseye_data,
            'tau_inter_line': tau_inter_line_data,
            'football': football_data
        }
        return data, 200
    elif page == "admin":

        all_stars_from_all_programs = np.concatenate(list(data_astroq[0].values()))

        # Get request frame table for all stars
        request_df = pl.get_request_frame(semester_planner, all_stars_from_all_programs)
        starinfo = request_df.to_dict(orient='records')

        lines = get_cof_data(all_stars_from_all_programs)
        cof_data = {
            'lines': lines
        }

        birdseye_data = {
            'starmap': star_obj.starmap.tolist(),
            'dates': semester_planner.add_dates_array.tolist(), 
        }

        tau_inter_line_data = get_tau_inter_line_data(all_stars_from_all_programs)
        football_data = get_football_data([all_stars_from_all_programs])

        data = {
            'starinfo': starinfo,
            'cof': cof_data,
            'birdseye': birdseye_data,
            'tau_inter_line': tau_inter_line_data,
            'football': football_data
        }
        return data, 200
    elif page == "nightplan":
        ladder_data = get_ladder_data()
        slew_animation_data = get_slew_animation_data()
        data = {
            'ladder_data': ladder_data,
            'slew_animation_data': slew_animation_data,
        }
        return jsonify(data), 200
    else:
        abort(404, description=f"Page '{page}' not found")

# Dynamic route for all pages


@app.route("/<semester_code>/<date>/<band>/<page>")
def dynamic_page(semester_code, date, band, page=None):
    """Handle all dynamic routes based on URL parameters"""
    # Validate parameters
    if band not in ['band1', 'band3']:
        abort(400, description="Band must be 'band1' or 'band3'")

    program_code = request.args.get('program_code')
    starname = request.args.get('starname')

    # Load data for this path
    if program_code is not None:
        # to get semester_planner and data_astroq
        success, message = load_data_for_path(
            semester_code, date, band, 'admin')
    else:
        success, message = load_data_for_path(semester_code, date, band, page)
    if not success:
        return f"Error: {message}", 404

    # Route to appropriate page based on parameters
    if starname is not None:
        # This is a star route
        return render_star_page(starname)
    elif page == "admin":
        return render_admin_page()
    elif page == "nightplan":
        return render_nightplan_page()
    elif program_code is not None:
        # This is a program route - check if it's a valid program code
        if program_code in data_astroq[0].keys():
            return render_program_page(program_code)
        else:
            # If not a program code, treat as a page
            page = program_code
            if page == "admin":
                return render_admin_page()
            elif page == "nightplan":
                return render_nightplan_page()
            else:
                abort(404, description=f"Page '{page}' not found")
    else:
        abort(404, description=f"Page '{page}' not found")


def render_admin_page():
    """Render the admin page"""
    if data_astroq is None:
        return "Error: No data available", 404

    all_stars_from_all_programs = np.concatenate(list(data_astroq[0].values()))

    # Get request frame table for all stars
    request_df = pl.get_request_frame(
        semester_planner, all_stars_from_all_programs)
    request_table_html = pl.dataframe_to_html(request_df)

    fig_cof = pl.get_cof(semester_planner, list(data_astroq[1].values()))
    fig_birdseye = pl.get_birdseye(
        semester_planner, data_astroq[2], list(data_astroq[1].values()))
    fig_football = pl.get_football(
        semester_planner, all_stars_from_all_programs, use_program_colors=True)
    fig_tau_inter_line = pl.get_tau_inter_line(
        semester_planner, all_stars_from_all_programs, use_program_colors=True)

    fig_cof_html = pio.to_html(fig_cof, full_html=True, include_plotlyjs='cdn')
    fig_birdseye_html = pio.to_html(
        fig_birdseye, full_html=True, include_plotlyjs='cdn')
    fig_football_html = pio.to_html(
        fig_football, full_html=True, include_plotlyjs='cdn')
    fig_tau_inter_line_html = pio.to_html(
        fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')

    figures_html = [fig_cof_html, fig_birdseye_html,
                    fig_tau_inter_line_html, fig_football_html]

    return render_template("admin.html", tables_html=[request_table_html], figures_html=figures_html)


def render_program_page(program_code):
    """Render the program overview page for a specific program"""
    if data_astroq is None:
        return "Error: No data available", 404

    # Get all stars in the specified program
    if program_code not in data_astroq[0]:
        return f"Error: Program {program_code} not found", 404

    program_stars = data_astroq[0][program_code]

    # Get request frame table for this program's stars
    request_df = pl.get_request_frame(semester_planner, program_stars)
    request_table_html = pl.dataframe_to_html(request_df)

    # Create overview figures for this program
    fig_cof = pl.get_cof(semester_planner, program_stars)
    fig_birdseye = pl.get_birdseye(
        semester_planner, data_astroq[2], program_stars)
    fig_tau_inter_line = pl.get_tau_inter_line(semester_planner, program_stars)
    fig_football = pl.get_football(semester_planner, program_stars)

    fig_cof_html = pio.to_html(fig_cof, full_html=True, include_plotlyjs='cdn')
    fig_birdseye_html = pio.to_html(
        fig_birdseye, full_html=True, include_plotlyjs='cdn')
    fig_tau_inter_line_html = pio.to_html(
        fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')
    fig_football_html = pio.to_html(
        fig_football, full_html=True, include_plotlyjs='cdn')

    figures_html = [fig_cof_html, fig_birdseye_html,
                    fig_tau_inter_line_html, fig_football_html]

    return render_template("semesterplan.html",
                           programname=program_code,
                           tables_html=[request_table_html],
                           figures_html=figures_html,
                           programs=[program_code])


def render_star_page(starname):
    """Render a specific star page"""
    if data_astroq is None:
        return "Error: No data available", 404

    compare_starname = starname.lower().replace(
        ' ', '')  # Lower case and remove all spaces
    program_dict = data_astroq[0]

    for program in program_dict.values():
        for star_obj in program:
            true_starname = star_obj.starname
            object_compare_starname = true_starname.lower().replace(' ', '')
            if object_compare_starname != compare_starname:
                continue
            # Get request frame table for this specific star
            request_df = pl.get_request_frame(semester_planner, [star_obj])
            request_table_html = pl.dataframe_to_html(request_df)

            fig_cof = pl.get_cof(semester_planner, [star_obj])
            fig_birdseye = pl.get_birdseye(
                semester_planner, data_astroq[2], [star_obj])
            fig_tau_inter_line = pl.get_tau_inter_line(
                semester_planner, [star_obj])
            fig_football = pl.get_football(semester_planner, [star_obj])

            fig_cof_html = pio.to_html(
                fig_cof, full_html=True, include_plotlyjs='cdn')
            fig_birdseye_html = pio.to_html(
                fig_birdseye, full_html=True, include_plotlyjs='cdn')
            fig_tau_inter_line_html = pio.to_html(
                fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')
            fig_football_html = pio.to_html(
                fig_football, full_html=True, include_plotlyjs='cdn')

            tables_html = [request_table_html]
            figures_html = [fig_cof_html, fig_birdseye_html,
                            fig_tau_inter_line_html, fig_football_html]

            return render_template("star.html", starname=true_starname, tables_html=tables_html, figures_html=figures_html)

    return f"Error, star {starname} not found in programs {list(program_dict.keys())}", 404


def render_nightplan_page():
    """Render the night plan page"""
    if night_planner is None:
        return "Error: No night planner data available", 404
    try:
        data_ttp = night_planner.solution
    except:
        return "Error: Night planner solution data not available", 404

    plots = ['script_table', 'slewgif', 'ladder', 'slewpath']

    script_table_df = pl.get_script_plan(night_planner)
    ladder_fig = pl.get_ladder(data_ttp)
    slew_animation_figures = pl.get_slew_animation(data_ttp, animationStep=120)
    slew_path_fig = pl.plot_path_2D_interactive(data_ttp)

    # Convert dataframe to HTML with unique table ID
    # Sort by starname (index 2) for better readability
    script_table_html = pl.dataframe_to_html(
        script_table_df, sort_column=0, page_size=100, table_id='script-table')
    # Convert figures to HTML
    ladder_html = pio.to_html(
        ladder_fig, full_html=True, include_plotlyjs='cdn')
    slew_path_html = pio.to_html(
        slew_path_fig, full_html=True, include_plotlyjs='cdn')

    # Convert matplotlib figures to GIF and then to HTML
    gif_frames = []
    for fig in slew_animation_figures:
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        gif_frames.append(iio.imread(buf))
        buf.close()

    gif_buf = BytesIO()
    iio.imwrite(gif_buf, gif_frames, format='gif', loop=0, duration=0.3)
    gif_buf.seek(0)

    gif_base64 = base64.b64encode(gif_buf.getvalue()).decode('utf-8')
    slew_animation_html = f'<img src="data:image/gif;base64,{gif_base64}" alt="Observing Animation"/>'
    gif_buf.close()

    figure_html_list = [script_table_html, ladder_html,
                        slew_animation_html, slew_path_html]

    return render_template("nightplan.html", starname=None, figure_html_list=figure_html_list,
                           semester_planner=semester_planner, night_planner=night_planner)


@app.route("/<semester_code>/<date>/<band>/download_nightplan")
def download_nightplan(semester_code, date, band):
    """Download the Magiq formatted night plan file"""
    semester_planner, night_planner

    # Validate parameters
    if band not in ['band1', 'band3']:
        abort(400, description="Band must be 'band1' or 'band3'")

    # Load data for this path
    success, message = load_data_for_path(
        semester_code, date, band, 'nightplan')  # to get night_planner
    # to get semester_planner and data_astroq
    success, message = load_data_for_path(semester_code, date, band, 'admin')
    if not success:
        return f"Error: {message}", 404

    if semester_planner is None or night_planner is None:
        return "Error: No planner data available", 404

    try:
        # Construct the path to the script file
        script_file_path = os.path.join(semester_planner.output_directory,
                                        f'script_{night_planner.current_day}_nominal.txt')

        if not os.path.exists(script_file_path):
            return "Error: Night plan file not found", 404

        # Return the file for download
        return send_from_directory(os.path.dirname(script_file_path),
                                   os.path.basename(script_file_path),
                                   as_attachment=True,
                                   download_name=f'script_{night_planner.current_day}_nominal.txt',
                                   mimetype='text/plain')

    except Exception as e:
        return f"Error downloading file: {str(e)}", 500


def launch_app():
    """Launch the Flask app"""
    app.run(host=gethostname(), debug=False, use_reloader=False, port=50002)


if __name__ == "__main__":
    launch_app()
