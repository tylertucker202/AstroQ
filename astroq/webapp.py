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
import astroq.splan as splan
import pdb

running_on_keck_machines = False

app = Flask(__name__, template_folder="../templates")

# Global variables to store loaded data
data_astroq = None
semester_planner = None
night_planner = None
uptree_path = '.' #TODO make config

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
                data_astroq = pl.process_stars(semester_planner) # writing data_astroq.pkl
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


# Dynamic data for all pages
@app.route("/data/<semester_code>/<date>/<band>/star/<starname>")
@app.route("/data/<semester_code>/<date>/<band>/<page>")
@app.route("/data/<semester_code>/<date>/<band>/<program_code>")
def dynamic_data(semester_code, date, band, page=None, starname=None, program_code=None):
    """Handle all dynamic routes based on URL parameters"""
    # Validate parameters
    if band not in ['band1', 'band3']:
        abort(400, description="Band must be 'band1' or 'band3'")
    
    # Load data for this path
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
        ladder_data = {}
        slew_animation_data = {}
        slew_path_data = {}
        data = {
            'ladder_data': ladder_data,
            'slew_animation_data': slew_animation_data,
            'slew_path_data': slew_path_data
        }
        return jsonify(data), 200

    elif program_code is not None:
        # This is a program route - check if it's a valid program code
        if program_code in data_astroq[0].keys():
            return render_program_page(semester_code, date, band, program_code)
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
        success, message = load_data_for_path(semester_code, date, band, 'admin') # to get semester_planner and data_astroq
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
            return render_program_page(semester_code, date, band, program_code)
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
    request_df = pl.get_request_frame(semester_planner, all_stars_from_all_programs)
    request_table_html = pl.dataframe_to_html(request_df)
    
    fig_cof = pl.get_cof(semester_planner, list(data_astroq[1].values()))
    fig_birdseye = pl.get_birdseye(semester_planner, data_astroq[2], list(data_astroq[1].values()))
    fig_football = pl.get_football(semester_planner, all_stars_from_all_programs, use_program_colors=True)
    fig_tau_inter_line = pl.get_tau_inter_line(semester_planner, all_stars_from_all_programs, use_program_colors=True)

    fig_cof_html = pio.to_html(fig_cof, full_html=True, include_plotlyjs='cdn')
    fig_birdseye_html = pio.to_html(fig_birdseye, full_html=True, include_plotlyjs='cdn')
    fig_football_html = pio.to_html(fig_football, full_html=True, include_plotlyjs='cdn')
    fig_tau_inter_line_html = pio.to_html(fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')
    
    figures_html = [fig_cof_html, fig_birdseye_html, fig_tau_inter_line_html, fig_football_html]

    return render_template("admin.html", tables_html=[request_table_html], figures_html=figures_html)

def render_program_page(semester_code, date, band, program_code):
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
    fig_birdseye = pl.get_birdseye(semester_planner, data_astroq[2], program_stars)
    fig_tau_inter_line = pl.get_tau_inter_line(semester_planner, program_stars)
    fig_football = pl.get_football(semester_planner, program_stars)

    fig_cof_html = pio.to_html(fig_cof, full_html=True, include_plotlyjs='cdn')
    fig_birdseye_html = pio.to_html(fig_birdseye, full_html=True, include_plotlyjs='cdn')
    fig_tau_inter_line_html = pio.to_html(fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')
    fig_football_html = pio.to_html(fig_football, full_html=True, include_plotlyjs='cdn')

    figures_html = [fig_cof_html, fig_birdseye_html, fig_tau_inter_line_html, fig_football_html]
    
    return render_template("semesterplan.html", 
                         programname=program_code, 
                         tables_html=[request_table_html], 
                         figures_html=figures_html, 
                         programs=[program_code])

def render_star_page(starname):
    """Render a specific star page"""
    if data_astroq is None:
        return "Error: No data available", 404
    
    compare_starname = starname.lower().replace(' ', '') # Lower case and remove all spaces
    program_names = data_astroq[0].keys()

    for program in program_names:
        for star_ind in range(len(data_astroq[0][program])):
            star_obj = data_astroq[0][program][star_ind]

            true_starname = star_obj.starname
            object_compare_starname = true_starname.lower().replace(' ', '')
            
            if object_compare_starname == compare_starname:
                # Get request frame table for this specific star
                request_df = pl.get_request_frame(semester_planner, [star_obj])
                request_table_html = pl.dataframe_to_html(request_df)

                fig_cof = pl.get_cof(semester_planner, [data_astroq[0][program][star_ind]])
                fig_birdseye = pl.get_birdseye(semester_planner, data_astroq[2], [star_obj])
                fig_tau_inter_line = pl.get_tau_inter_line(semester_planner, [star_obj])
                fig_football = pl.get_football(semester_planner, [star_obj])

                fig_cof_html = pio.to_html(fig_cof, full_html=True, include_plotlyjs='cdn')
                fig_birdseye_html = pio.to_html(fig_birdseye, full_html=True, include_plotlyjs='cdn')
                fig_tau_inter_line_html = pio.to_html(fig_tau_inter_line, full_html=True, include_plotlyjs='cdn')
                fig_football_html = pio.to_html(fig_football, full_html=True, include_plotlyjs='cdn')

                tables_html = [request_table_html]
                figures_html = [fig_cof_html, fig_birdseye_html, fig_tau_inter_line_html, fig_football_html]

                return render_template("star.html", starname=true_starname, tables_html=tables_html, figures_html=figures_html)
    
    return f"Error, star {starname} not found in programs {list(program_names)}"

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
    script_table_html = pl.dataframe_to_html(script_table_df, sort_column=0, page_size=100, table_id='script-table')
    # Convert figures to HTML
    ladder_html = pio.to_html(ladder_fig, full_html=True, include_plotlyjs='cdn')
    slew_path_html = pio.to_html(slew_path_fig, full_html=True, include_plotlyjs='cdn')
    
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
    
    figure_html_list = [script_table_html, ladder_html, slew_animation_html, slew_path_html]

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
    success, message = load_data_for_path(semester_code, date, band, 'nightplan') # to get night_planner
    success, message = load_data_for_path(semester_code, date, band, 'admin') # to get semester_planner and data_astroq
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
