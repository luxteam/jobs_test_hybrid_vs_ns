import argparse
import os
import subprocess
import psutil
import json
import platform
from datetime import datetime
from shutil import copyfile, move, which
import sys
from utils import is_case_skipped
from queue import Queue
from subprocess import PIPE, Popen
from threading import Thread
import copy
import traceback
import time
import win32gui
import win32con

sys.path.append(os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
from jobs_launcher.core.config import *
from jobs_launcher.core.system_info import get_gpu


def copy_test_cases(args):
    try:
        copyfile(os.path.realpath(os.path.join(os.path.dirname(
            __file__), '..', 'Tests', args.test_group, 'test_cases.json')),
            os.path.realpath(os.path.join(os.path.abspath(
                args.output), 'test_cases.json')))

        cases = json.load(open(os.path.realpath(
            os.path.join(os.path.abspath(args.output), 'test_cases.json'))))

        with open(os.path.join(os.path.abspath(args.output), "test_cases.json"), "r") as json_file:
            cases = json.load(json_file)

        if os.path.exists(args.test_cases) and args.test_cases:
            with open(args.test_cases) as file:
                test_cases = json.load(file)['groups'][args.test_group]
                if test_cases:
                    necessary_cases = [
                        item for item in cases if item['case'] in test_cases]
                    cases = necessary_cases

            with open(os.path.join(args.output, 'test_cases.json'), "w+") as file:
                json.dump(duplicated_cases, file, indent=4)
    except Exception as e:
        main_logger.error('Can\'t load test_cases.json')
        main_logger.error(str(e))
        exit(-1)


def prepare_empty_reports(args, current_conf):
    main_logger.info('Create empty report files')

    copyfile(os.path.abspath(os.path.join(args.output, '..', '..', '..', '..', 'jobs_launcher',
                                          'common', 'img', 'error.jpg')), os.path.join(args.output, 'Color', 'failed.jpg'))

    copyfile(os.path.abspath(os.path.join(args.output, '..', '..', '..', '..', 'jobs_launcher',
                                          'common', 'img', 'crash.jpg')), os.path.join(args.output, 'Color', 'crash.jpg'))

    with open(os.path.join(os.path.abspath(args.output), "test_cases.json"), "r") as json_file:
        cases = json.load(json_file)

    for case in cases:
        if is_case_skipped(case, current_conf):
            case['status'] = 'skipped'

        if case['status'] != 'done' and case['status'] != 'error':
            if case["status"] == 'inprogress':
                case['status'] = 'active'

            test_case_report = RENDER_REPORT_BASE.copy()
            test_case_report['test_case'] = case['case']
            test_case_report['render_device'] = get_gpu()
            test_case_report['render_duration'] = -0.0
            test_case_report['script_info'] = case['script_info']
            test_case_report['geometry'] = case['geometry']
            test_case_report['material_file'] = case['material_file']
            test_case_report['material_path'] = case['material_path']
            test_case_report['plugin'] = args.plugin
            test_case_report['render_engine'] = args.plugin
            test_case_report['iterations'] = int(case.get('iterations', 50))
            test_case_report['test_group'] = args.test_group
            test_case_report['tool'] = 'HybridVsNs'
            test_case_report['render_log'] = ''
            test_case_report['date_time'] = datetime.now().strftime(
                '%m/%d/%Y %H:%M:%S')
            test_case_report['is_crash'] = False
            if case['status'] == 'skipped':
                test_case_report['test_status'] = 'skipped'
                test_case_report['file_name'] = case['case'] + case.get('extension', '.jpg')
                test_case_report['render_color_path'] = os.path.join('Color', test_case_report['file_name'])
                test_case_report['group_timeout_exceeded'] = False

                try:
                    skipped_case_image_path = os.path.join(args.output, 'Color', test_case_report['file_name'])
                    if not os.path.exists(skipped_case_image_path):
                        copyfile(os.path.join(args.output, '..', '..', '..', '..', 'jobs_launcher', 
                            'common', 'img', "skipped.jpg"), skipped_case_image_path)
                except OSError or FileNotFoundError as err:
                    main_logger.error("Can't create img stub: {}".format(str(err)))
            else:
                test_case_report['test_status'] = 'error'
                test_case_report['file_name'] = 'failed.jpg'
                test_case_report['render_color_path'] = os.path.join('Color', 'failed.jpg')

            case_path = os.path.join(args.output, case['case'] + CASE_REPORT_SUFFIX)

            if os.path.exists(case_path):
                with open(case_path) as f:
                    case_json = json.load(f)[0]
                    test_case_report["number_of_tries"] = case_json["number_of_tries"]

            with open(case_path, "w") as f:
                f.write(json.dumps([test_case_report], indent=4))

    with open(os.path.join(args.output, "test_cases.json"), "w+") as f:
        json.dump(cases, f, indent=4)


def read_output(pipe, functions):
    for line in iter(pipe.readline, b''):
        for function in functions:
            function(line.decode('utf-8'))
    pipe.close()


def save_results(args, case, cases, test_case_status, render_time, error_messages = [], is_crash = False):
    with open(os.path.join(args.output, case["case"] + CASE_REPORT_SUFFIX), "r") as file:
        test_case_report = json.loads(file.read())[0]
        test_case_report["file_name"] = case["case"] + case.get("extension", '.jpg')
        test_case_report["render_color_path"] = os.path.join("Color", test_case_report["file_name"])
        test_case_report["test_status"] = test_case_status
        test_case_report["render_time"] = render_time
        test_case_report["render_log"] = os.path.join("render_tool_logs", case["case"] + ".log")
        test_case_report["testing_start"] = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        test_case_report["number_of_tries"] += 1
        test_case_report["is_crash"] = is_crash

        if test_case_status != "passed":
            if is_crash:
                copyfile(os.path.join(args.output, "Color", "crash.jpg"), 
                    os.path.join(args.output, "Color", case["case"] + ".jpg"))
                test_case_report["message"] = list(error_messages)
            else:
                copyfile(os.path.join(args.output, "Color", "failed.jpg"), 
                    os.path.join(args.output, "Color", case["case"] + ".jpg"))
                test_case_report["message"] = list(error_messages)

        if test_case_status == "passed" or test_case_status == "error":
            test_case_report["group_timeout_exceeded"] = False

    with open(os.path.join(args.output, case["case"] + CASE_REPORT_SUFFIX), "w") as file:
        json.dump([test_case_report], file, indent=4)

    case["status"] = test_case_status
    with open(os.path.join(args.output, "test_cases.json"), "w") as file:
        json.dump(cases, file, indent=4)


def execute_tests(args, current_conf):
    rc = 0

    with open(os.path.join(os.path.abspath(args.output), "test_cases.json"), "r") as json_file:
        cases = json.load(json_file)

    for case in [x for x in cases if not is_case_skipped(x, current_conf)]:

        current_try = 0

        error_messages = set()

        is_crash = False

        while current_try < args.retries:
            is_crash = False

            try:
                execution_script = "{tool} --plugin {plugin} --geometry {geometry} --material {material} --path {path} --output {output} --iterations {iterations} --flip_y 1"

                image_output_path = os.path.abspath(os.path.join(args.output, "Color", case["case"] + case.get("extension", ".jpg")))

                execution_script = execution_script.format(tool=args.tool, plugin=args.plugin, 
                    geometry=os.path.abspath(os.path.join(args.res_path, case["geometry"])), 
                    material=case["material_file"], 
                    path=os.path.abspath(os.path.join(args.res_path, case["material_path"])), 
                    output=image_output_path,
                    iterations=case.get("iterations", 50)
                )

                execution_script_path = os.path.join(args.output, "{}.bat".format(case["case"]))
       
                with open(execution_script_path, "w") as f:
                    f.write(execution_script)

                status = "error"

                p = psutil.Popen(execution_script_path, shell=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                outs = []
                errs = []
                queue = Queue()

                stdout_thread = Thread(target=read_output, args=(p.stdout, [queue.put, outs.append]))
                stderr_thread = Thread(target=read_output, args=(p.stderr, [queue.put, errs.append]))

                start_time = time.time()

                for thread in (stdout_thread, stderr_thread):
                    thread.daemon = True
                    thread.start()

                try:
                    while True:
                        try:
                            p.wait(timeout=5)

                            for out in outs:
                                if "error code" in out:
                                    raise Exception("Tool returned error code")

                            if not os.path.exists(image_output_path):
                                # Image not found - crash
                                is_crash = True
                                raise Exception("Output image not found")

                            status = "passed"

                            render_time = time.time() - start_time

                            save_results(args, case, cases, "passed", render_time)
                        except (psutil.TimeoutExpired, subprocess.TimeoutExpired) as e:
                            crash_window = win32gui.FindWindow(None, "HybridVsNs.exe")

                            while crash_window != 0:
                                win32gui.PostMessage(crash_window, win32con.WM_CLOSE, 0, 0)

                                is_crash = True
                                crash_window = win32gui.FindWindow(None, "HybridVsNs.exe")

                            if is_crash:
                                raise Exception("Crash window found")
                        else:
                            break
                except Exception as e:
                    main_logger.error("Test case {} has been aborted due to error: {}".format(case["case"], e))
                    for child in reversed(p.children(recursive=True)):
                        child.terminate()
                    p.terminate()

                    raise e
                finally:
                    log_path = os.path.join(args.output, "render_tool_logs", case["case"] + ".log")

                    outs = " ".join(outs)
                    errs = " ".join(errs)

                    with open(log_path, "a", encoding="utf-8") as file:
                        file.write("---------- Try #{} ----------".format(current_try))
                        file.write(outs)
                        file.write(errs)

                break
            except Exception as e:
                save_results(args, case, cases, "failed", -0.0, error_messages = error_messages, is_crash = is_crash)
                error_messages.add(str(e))
                main_logger.error("Failed to execute test case (try #{}): {}".format(current_try, str(e)))
                main_logger.error("Traceback: {}".format(traceback.format_exc()))
            finally:
                current_try += 1
        else:
            main_logger.error("Failed to execute case '{}' at all".format(case["case"]))
            rc = -1
            save_results(args, case, cases, "error", -0.0, error_messages = error_messages, is_crash = is_crash)

    return rc


def createArgsParser():
    parser = argparse.ArgumentParser()

    parser.add_argument("--tool", required=True, metavar="<path>")
    parser.add_argument("--output", required=True, metavar="<dir>")
    parser.add_argument("--test_group", required=True)
    parser.add_argument("--res_path", required=True)
    parser.add_argument("--test_cases", required=True)
    parser.add_argument("--retries", required=False, default=2, type=int)
    parser.add_argument('--timeout', required=False, default=300)
    parser.add_argument('--plugin', required=True)

    return parser


if __name__ == '__main__':
    main_logger.info('simpleRender start working...')

    args = createArgsParser().parse_args()

    try:
        os.makedirs(args.output)

        if not os.path.exists(os.path.join(args.output, "Color")):
            os.makedirs(os.path.join(args.output, "Color"))
        if not os.path.exists(os.path.join(args.output, "render_tool_logs")):
            os.makedirs(os.path.join(args.output, "render_tool_logs"))

        render_device = get_gpu()
        system_pl = platform.system()
        current_conf = set(platform.system()) if not render_device else {platform.system(), render_device}
        main_logger.info("Detected GPUs: {}".format(render_device))
        main_logger.info("PC conf: {}".format(current_conf))
        main_logger.info("Creating predefined errors json...")

        copy_test_cases(args)
        prepare_empty_reports(args, current_conf)
        exit(execute_tests(args, current_conf))
    except Exception as e:
        main_logger.error("Failed during script execution. Exception: {}".format(str(e)))
        main_logger.error("Traceback: {}".format(traceback.format_exc()))
        exit(-1)
