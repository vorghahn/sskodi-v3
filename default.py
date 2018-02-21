import sys,os

if __name__ == '__main__':
    arg = None
    if len(sys.argv) > 1: arg = sys.argv[1] or False

    if arg == 'REFRESH_SCHEDULE':
        from lib import smoothstreams
        smoothstreams.Schedule.sscachejson(force=True)
    elif arg == 'ABOUT':
        from lib import util
        util.about()
    elif arg == 'DOWNLOAD_CALLBACK':
        from lib.smoothstreams import player
        player.downloadCallback(sys.argv[2])
    elif arg == 'REFRESH_HASH':
        from lib import util
        hashFile = os.path.join(util.PROFILE,'hash')
        if os.path.exists(hashFile):
            os.remove(hashFile)
        from lib.smoothstreams import player
        player.ChannelPlayer().login()
        try:
            hash = util.getSetting('SHash_0')
        except:
            hash = util.getSetting('SHash_1')
        with open(hashFile,'w') as f:

            f.write(str(hash))
    else:
        from ssmain import main
        main()