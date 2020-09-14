import gridlabd
import traceback
import os
import sys, getopt
import data_post_process

path = ''
modelinputfile = ''
outputfile = ''
compile_flag = 0
baseline_flag = 0


def command_line_template():
    sys.stderr.write('run_gridlabd_main.py -C -B -W <inputfilepath> -i <modelinputfile> -o <outputfile>')
    sys.stderr.write('-C : [OPTIONAL] Compile flag for GridLAB-D.')
    sys.stderr.write('-B : [OPTIONAL] Flag that indicates that the baseline run is triggered.')
    sys.stderr.write('-W : [OPTIONAL] Specifies folder location of GLM file, if not specified assumes current folder.')
    sys.stderr.write('-i : [REQUIRED] Name of the model input file')
    sys.stderr.write('-o : [OPTIONAL] JSON dump file name.')
    return True


try:
    try:
        opts, args = getopt.getopt(sys.argv[1:], "CBW:i:o:", ["Wfile=", "ifile=", "ofile="])
    except getopt.GetoptError:
        sys.stderr.write('Incorrect command arguments')
        command_line_template()
        sys.exit(2)
    if not opts:
        sys.stderr.write('Missing command arguments')
        command_line_template()
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-C':
            compile_flag = 1
        elif opt in ("-W", "--Wfile"):
            path = arg
        elif opt in ("-B", "--Bfile"):
            baseline_flag = 1  # setting the baseline flag to true
        elif opt in ("-i", "--ifile"):
            modelinputfile = arg
        elif opt in ("-o", "--ofile"):
            outputfile = arg
        else:
            print("ERROR: Incorrect argument set: python3 [file] -W [path] -i [modelinputfile] -o [outputfile]")
    if path:
        print("Setting path to folder: ", path)
        os.chdir(path)
    else:
        print("Setting path to current folder")

    gridlabd.command('--profile')
    gridlabd.command('--version')
    gridlabd.command('--relax')
    if compile_flag == 1:
        print("Compile Flag is Set")
        gridlabd.command('-C')
    gridlabd.command('--redirect')
    gridlabd.command('all')

    if baseline_flag == 1 and compile_flag == 1:
        sys.stderr.write('Compile flag and baseline flag can not be set simultanaeously.')
        sys.exit(3)
    if baseline_flag == 1 and compile_flag != 1:
        print("Baseline Flag Set")
        gridlabd.command('-D')
        gridlabd.command('BASELINE=yes')
    gridlabd.command(modelinputfile)
    if outputfile:
        gridlabd.command('-o')
        gridlabd.command(outputfile)
    gridlabd.start('wait')
    print('\n')
    if os.stat('gridlabd.err').st_size == 0:
        print('No errors in file.')
    else:
        sys.stderr.write('Error(s) found in the model, printing gridlabd.err file contents...')
        fr_err = open('gridlabd.err', 'r')
        sys.stderr.write(fr_err.read())
        sys.exit(3)
    if os.stat('gridlabd.wrn').st_size == 0:
        print('No errors in file.')
    else:
        print('Warning(s) found in the model, printing gridlabd.wrn file contents...')
        fr_wrn = open('gridlabd.wrn', 'r')
        print(fr_wrn.read())
    if compile_flag != 1 and baseline_flag == 0:
        data_post_process.log_gen()
        data_post_process.timeseries_gen()
    if baseline_flag == 1:
        data_post_process.timeseries_persupernode(runname='baseline')

except Exception as e:
    sys.stderr.write(f'Unhandled Exception in run_gridlabd_main.py: {e}')
    sys.stderr.write(traceback.format_exc())
    raise e
