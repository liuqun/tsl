import os
import subprocess
import sys

from waflib import Logs
from waflib.Errors import WafError

#For help, type this command:
#
#   ./waf -h

#To build, type this command (parallelism is automatic, -jX is optional):
#
#   ./waf configure clean build

########## Configuration ##########

#waf internal
top = '.'
out = 'build'

versionCommand = 'git describe --abbrev=16 --dirty --always --tags'.split(' ')
cpuArchCommand = '/bin/uname -m'.split(' ')

# FIXME: get rid of this crap
cpuArch = subprocess.check_output(cpuArchCommand).strip().decode('utf-8')

def _checkSupportedArch(cpuArchId):
	if cpuArchId != 'x86_64' and cpuArchId != 'armv7l' and cpuArchId != 'aarch64':
		raise Exception('Unsupported CPU architecture: {}'.format(cpuArchId))

########## Commands ##########

def _loadTools(context):
	_checkSupportedArch(cpuArch)

	#Force gcc (instead of generic C) since Phil tortures the compiler
	context.load('gcc')

	# Nasm/Yasm
	if cpuArch == 'x86_64':
		context.load('nasm')

	#This does neat stuff, like header dependencies
	context.load('c_preproc')

def options(opt):
	#argparse style options (yay!)
	opt.add_option('-d', '--debug', action='store_true',
		help='Debug mode (turns on debug defines, assertions, etc.) - a superset of -D')
	opt.add_option('-D', '--tsl-debug', action='store_true',
		help='Defines _TSL_DEBUG (even for release builds!)')

	_loadTools(opt)

def configure(conf):
	_loadTools(conf)

	conf.check(lib='ck', uselib='CK', define_name='HAVE_CONCURRENCYKIT', msg='Checking for ConcurrencyKit')
	conf.check(lib='jansson', uselib='JANSSON', define_name='HAVE_JANSSON', msg='Checking for Jansson (JSON library)')

	#Setup build flags
	conf.env.CFLAGS += [
		'-g3',
		'-gdwarf-4',

		'-Wall',
		'-Wundef',
		'-Wstrict-prototypes',
		'-Wmissing-prototypes',
		'-Wno-trigraphs',
		# '-Wconversion', -- this is a massive undertaking to turn back on, lazy.

		'-fno-strict-aliasing',
		'-fno-common',

		'-Werror-implicit-function-declaration',
		'-Wno-format-security',

		'-fno-delete-null-pointer-checks',

		'-Wuninitialized',
		'-Wmissing-include-dirs',

		'-Wshadow',
		# '-Wcast-qual',

		'-Wframe-larger-than=2047',

		'-std=c11',

		'-g',

		'-rdynamic',
	]

	conf.env.DEFINES += [
		'_ATS_IN_TREE',
		'_GNU_SOURCE',
		'SYS_CACHE_LINE_LENGTH=64',
	]

	conf.env.INCLUDES += [
		'.'
	]

	# FIXME: this is not sane for a lot of environments
	conf.env.LIBPATH += [
		'/usr/local/lib',
	]

	conf.env.LIB += [
		'pthread',
		'rt',
		'jansson',
		'dl',
		'm',
	]

	conf.env.LDFLAGS += [
		'-rdynamic'
	]

	# Assembler flags (so that the linker will understand the objects)
	if cpuArch == 'x86_64':
		conf.env.ASFLAGS += ['-f', 'elf64']

	conf.msg('Building for:', cpuArch)

	conf.msg('Install prefix:', conf.env.PREFIX)

	tuning = []
	if cpuArch == 'armv7l':
		# ARM can be a bit quirky. Make sure we specify the right CPU architecture,
		# and ensure we have the right register set defined.
		# Also, for now, we shall asume we have NEON available, all the time.
		conf.env.DEFINES += [ '_USE_ARM_NEON' ]
		tuning = [
			'-mcpu=cortex-a7',
			'-mfpu=crypto-neon-fp-armv8',
			'-mfloat-abi=hard',
		]
	elif cpuArch == 'aarch64':
		conf.env.LIBPATH += [ '/usr/lib/aarch64-linux-gnu' ],
		conf.env.DEFINES += [ '_USE_ARM_NEON' ]
		tuning = [
			'-mcpu=cortex-a53',
		]
	else:
		conf.env.LIBPATH += [ '/usr/lib/x86_64-linux-gnu' ],
		tuning = [
			'-march=native',
			'-mtune=native',
		]

	#Setup the environment: debug or release
	if conf.options.debug:
		stars = '*' * 20
		conf.msg('Build environment', '%s DEBUG %s' % (stars, stars), color='RED')
		conf.env.ENVIRONMENT = 'debug'
		conf.env.CFLAGS += [
			'-O0',
		] + tuning
	else:

		stars = '$' * 20
		conf.msg('Build environment', '%s RELEASE %s' % (stars, stars), color='BOLD')
		conf.env.ENVIRONMENT = 'release'
		conf.env.CFLAGS += [
			'-O2',
		] + tuning

	if conf.options.debug or conf.options.tsl_debug:
		conf.msg('Defining', '_TSL_DEBUG', color='CYAN')
		conf.env.DEFINES += [
			'_TSL_DEBUG',
		]

	if conf.options.debug:
		conf.env.DEFINES += [
			'_AWESOME_PANIC_MESSAGE',
		]
	else:
		conf.env.DEFINES += [
			'NDEBUG', #Make assert() compile out in production
		]

	# TODO: per-architecture, define the size of a pointer
	conf.env.DEFINES += [
		'TSL_POINTER_SIZE=8',
	]

	# App Specific: Defines where to look for configs by default
	conf.env.DEFINES += [
		'CONFIG_DIRECTORY_DEFAULT=\"/etc/tsl\"',
	]

def _preBuild(bld):
	Logs.info('Pre %s...' % bld.cmd)

	#This gets executed after build() sets up the build, but before it actually happens

def _postBuild(bld):
	Logs.info('Post %s...' % bld.cmd)

	environment = bld.env.ENVIRONMENT
	if environment == 'debug':
		stars = '*' * 20
		Logs.error('Finished building: %s DEBUG [%s] %s' % (stars, bld.env.VERSION, stars))
	else:
		stars = '$' * 20
		Logs.info('Finished building: %s RELEASE [%s] %s' % (stars, bld.env.VERSION, stars))

	#Symlink latest
	os.system('cd "%s" && ln -fns "%s" latest' % (bld.out_dir, environment))

def build(bld):
	#This method gets called when the dependency tree needs to be computed, NOT
	#just on 'build' (e.g. it also is called for 'clean').

	#Check the version immediately before the build happens
	import subprocess
	try:
		version = subprocess.check_output(versionCommand).strip().decode('utf-8')
		Logs.info('Building version %s' % version)
	except subprocess.CalledProcessError:
		version = 'NotInGit'
		Logs.warn('Building out of version control, so no version string is available')
	bld.env.VERSION = version

	#Pre and post build hooks (these are only called for 'build')
	bld.add_pre_fun(_preBuild)
	bld.add_post_fun(_postBuild)

	#Construct paths for the targets
	basePath = bld.env.ENVIRONMENT
	binPath = os.path.join(basePath, 'bin')
	libPath = os.path.join(basePath, 'lib')
	testPath = os.path.join(basePath, 'test')

	#app
	appExcl = []
	if cpuArch == 'armv7l' or cpuArch == 'aarch64':
		# We want to ignore the CPU features check, since this relies on x86 CPUID
		appExcl.append('app/cpufeatures.*')
	bld.stlib(
		source   = bld.path.ant_glob('app/*.c', excl=appExcl),
		use      = ['tslconfig', 'tsl'],
		target   = os.path.join(libPath, 'tslapp'),
		install_path = os.path.join(bld.env.PREFIX, 'lib'),
		name     = 'tslapp',
	)
	bld.program(
		source   = bld.path.ant_glob('app/test/*.c'),
		use      = ['tslapp', 'tsltest', 'tsl'],
		target   = os.path.join(testPath, 'test_app'),
		name     = 'test_app',
	)
	bld.install_files('${PREFIX}/include/tsl/app', bld.path.ant_glob('app/**/*.h'))

	#config
	bld.stlib(
		source   = bld.path.ant_glob('config/*.c'),
		use      = ['tsl'],
		target   = os.path.join(libPath, 'tslconfig'),
		install_path = os.path.join(bld.env.PREFIX, 'lib'),
		name     = 'tslconfig',
	)
	bld.program(
		source   = bld.path.ant_glob('config/test/*.c'),
		use      = ['tslconfig', 'tsltest', 'tsl'],
		target   = os.path.join(testPath, 'test_config'),
		name     = 'test_config',
	)
	bld.install_files('${PREFIX}/include/tsl/config', bld.path.ant_glob('config/**/*.h'))

	#test
	bld.stlib(
		source   = bld.path.ant_glob('test/*.c'),
		use      = ['tslapp'],
		target   = os.path.join(libPath, 'tsltest'),
		install_path = os.path.join(bld.env.PREFIX, 'lib'),
		name     = 'tsltest',
	)
	bld.install_files('${PREFIX}/include/tsl/test', bld.path.ant_glob('test/**/*.h'))

	#TSL
	#Version objects are built specially first since they have a special define
	versionDefine = '_VC_VERSION=\"%s\"' % bld.env.VERSION
	bld.objects(
		defines  = [versionDefine],
		source   = 'tsl/version.c',
		target   = 'tsl_version',
		name     = 'tsl_version',
	)
	#Then the regular build happens

	# Calculate what we might want to exclude for certain architectures
	excl=['tsl/version.c', 'tsl/test/*.*']
	if cpuArch == 'armv7l' or cpuArch == 'aarch64':
		# We want to ignore coro - there's no ARM implementation yet
		excl.append('tsl/coro/*.*')
		excl.append('tsl/timer.c')

	tslSource = bld.path.ant_glob('tsl/**/*.[cS]', excl=excl)
	bld.stlib(
		cflags   = ['-fPIC'],
		source   = tslSource,
		use      = ['tsl_version'],
		target   = os.path.join(libPath, 'tsl'),
		install_path = os.path.join(bld.env.PREFIX, 'lib'),
		name     = 'tsl',
	)

	# Exclude the coroutine tests if we're building for ARM32
	excl=[]
	if cpuArch == 'armv7l' or cpuArch == 'aarch64':
		excl.append('tsl/test/test_coro.c')
		excl.append('tsl/test/test_speed.c')
	bld.program(
		source   = bld.path.ant_glob('tsl/test/*.c', excl=excl),
		use      = ['tsl'],
		target   = os.path.join(testPath, 'test_tsl'),
		name     = 'tsl_test',
	)
	bld.program(
		source   = bld.path.ant_glob('tsl/version_dump/*.c'),
		use      = ['tsl'],
		target   = os.path.join(binPath, 'dump_version'),
		name     = 'dump_version',
	)
	bld.install_files('${PREFIX}/include/tsl/tsl', bld.path.ant_glob('tsl/**/*.h'))

	# Build the pkg-config file
	bld(source='tsl.pc.in', VERSION=bld.env.VERSION,
		INCLUDEDIR=os.path.join(bld.env.PREFIX,'include', 'tsl'),
		LIBDIR=os.path.join(bld.env.PREFIX, 'lib'))

from waflib.Build import BuildContext
class TestContext(BuildContext):
        cmd = 'test'
        fun = 'test'

def test(ctx):
	Logs.info('Unit testing... TODO')

class PushContext(TestContext):
        cmd = 'push'
        fun = 'push'

def sysinstall(ctx):
	Logs.info('Installing system packages...')

	packages = [
		'build-essential',
		'pkg-config',
		'libjansson-dev',
	]

	os.system('apt-get install %s' % ' '.join(packages))

