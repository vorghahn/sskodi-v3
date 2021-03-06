
import xbmc, xbmcgui
import os
import datetime
import threading
import URLDownloader
from . import util
from . import kodigui
from . import smoothstreams
from .downloadregistry import DownloadRegistry

DOWNLOADER = None

API_LEVEL = 1

def versionCheck():
    old = util.getSetting('API_LEVEL',0)
    if API_LEVEL == old: return False
    util.setSetting('API_LEVEL',API_LEVEL)
    if old == 0:
        util.LOG('FIRST RUN')
    return False

#==============================================================================
# ViewManager
#==============================================================================
class ViewManager(object):
    def __init__(self):
        self.valid = 1
        self.initialize()
        if self.valid == 1:
            util.openSettings()
        else:
            self.start()

    @util.busyDialog
    def initialize(self):
        self.schedule = ''
        self.channels = ''

        self.schedule1 = ''
        self.channels1 = ''
        self.player = smoothstreams.player.ChannelPlayer()
        
        #Check for valid credential
        #If user has entered wrong credential then, login will be failed
        vHash = self.player.loadHash()
        if not vHash: vHash = self.player.getHash()
        if 'error' in vHash:
            xbmcgui.Dialog().ok("Validation",vHash['error'])
            self.valid = 1
            return
        
        if util.getSetting('theme') == 'true':
            self.theme = 'modern'
        else:
            self.theme = 'classic'
        
        self.player.testServers() #Test if auto server is enabled
        self.player.resetTokens() #Tokens seem to become invalid over time. Reset on startup to keep them fresh
        self.setutcOffsetMinutes()
        self.createFav()
        util.DEBUG_LOG('Timezone: {0}'.format(smoothstreams.timeutils.LOCAL_TIMEZONE))
        self.initDisplayOffset()
        self.initChannels()
        self._lastStartOfDay = self.startOfDay()
        self.window = None
        self.mode = None
        self.cron = None
        self.search_key = ''
        if util.getSetting('mode') == 'List':
            self.mode = 'CATS'
        elif util.getSetting('mode') == 'EPG':
            self.mode = 'EPG'
        elif util.getSetting('mode') == 'Panel':
            self.mode = 'PANEL'
            if util.getSetting('theme') == 'false':
                util.setSetting('mode', 'List')
                self.mode = 'CATS'
        else:
            self.mode = util.getSetting('last_mode') or 'CATS'
        self.valid = 0

    def start(self):
        with util.Cron(5) as self.cron:
            self._start()

    def _start(self):
        while self.mode:
            if self.mode == 'EPG':
                self.showEPG()
            elif self.mode == 'CATS':
                self.showCats()
            else:
                self.showPanel()
        util.DEBUG_LOG('EXIT')

    def switch(self,mode):
        self.mode = mode
        if self.window: self.window.close()

    def timerCallback(self):
        if not self.window: return
        self.window.timerCallback()

    def reloadChannels(self,force=False):
        fetch = {   'guide':'feed-new-latest.zip',
                    'guide_json':'feed-new.json',
                    'full_guide':'feed-new-full-latest.zip',
                    'full_guide_json':'feed-new-full.json'}
        LIST = util.getSetting('mode')
        if util.getSetting('full_guide_switch') == 'false' or LIST == "List":
            smoothstreams.Schedule.sscachejson(fetch['guide'],fetch['guide_json'],age=3600)
        else:
            smoothstreams.Schedule.sscachejson(fetch['full_guide'],fetch['full_guide_json'],age=3600)
            
        #if self.schedule.sscachejson(force):
        self.updateChannels()

    def updateChannels(self):
        self.channels = self.schedule.epg(self.startOfDay())
        self.initChannels()

    def isNewDay(self):
        sod = self.startOfDay()
        if sod == self._lastStartOfDay: return False
        self._lastStartOfDay = sod
        return True

    def setEPGLimits(self):
        self.upperLimit = self.displayOffset + (24 * 60 * util.getSetting("schedule_plus_limiter",3))
        self.lowerLimit = self.displayOffset - (24 * 60 * util.getSetting("schedule_minus_limiter",2))

    def getChannel(self, number):
        if str(number).startswith('0'):
            number = str(number)[1]
        for c in self.channels if util.getSetting('mode') == 'EPG' else self.channels1:
            if number == c.get('ID'):
                return c

    def changeCat(self):
        if util.getSetting('show_all',bool) == 'true':
            categories = ["show_30401","show_30404","show_30405","show_30408","show_30409","show_30410","show_30411","show_30412","show_30415","show_30416","show_30417","show_30418","show_30419","show_30420","show_30421"]
            for cat in categories:
                util.setSetting(cat,'true')

    def showEPG(self):
        util.setSetting('last_mode','EPG')
        self.window = KodiEPGDialog('script-smoothstreams-epg.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)
        self.changeCat()
        self.window.doModal()
        self.window.onClosed()
        del self.window
        self.window = None

    def showCats(self):
        util.setSetting('last_mode','CATS')
        self.window = KodiListDialog('script-smoothstreams-category.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)
        self.changeCat()
        self.window.doModal()
        self.window.onClosed()
        del self.window
        self.window = None
        util.DEBUG_LOG('List Done')

    def showPanel(self):
        util.setSetting('last_mode','PANEL')
        self.window = KodiListDialog('script-smoothstreams-panel.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)
        self.changeCat()
        self.window.doModal()
        self.window.onClosed()
        del self.window
        self.window = None
        util.DEBUG_LOG('List Done')

    def doChannelEntry(self,digit):
        window = KodiChannelEntry('script-smoothstreams-channel_entry.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self,digit=digit)
        window.doModal()
        ret = None
        if window.set:
            ret = window.digits
        del window
        return ret

    def checkChannelEntry(self,action):
        if action.getId() >= xbmcgui.REMOTE_0 and action.getId() <= xbmcgui.REMOTE_9:
            self.doChannelEntry(str(action.getId() - 58))
            return True
        return False

    def createCategoryFilter(self):
        if util.getSetting('show_all',True): return None

        cats = (    ('American Football',('NCAAF', 'NFL')),
                    ('Baseball', None),
                    ('Basketball', ('NBA', 'NCAAB')),
                    ('Boxing + MMA', None),
                    ('Cricket', None),
                    ('Golf', None),
                    ('Ice Hockey', None),
                    ('Motor Sports', ('Formula 1', 'Nascar')),
                    ('Olympics', None),
                    ('Other Sports', None),
                    ('Rugby', None),
                    ('Tennis', None),
                    ('TV Shows', None),
                    ('World Football', None),
                    ('Wrestling', None)
        )
        catFilter = []
        si=0
        for cat, subs in cats:
            si+=1
            if util.getSetting('show_{0}'.format(30400+si),True):
                if subs:
                    add = []
                    hide1 = False
                    for s in subs:
                        si+=1
                        if util.getSetting('show_{0}'.format(30400+si),True):
                            add.append(s)
                        else:
                            hide1 = True
                    if hide1:
                        catFilter += add
                    else:
                        catFilter.append(cat)
                else:
                    catFilter.append(cat)
            else:
                if subs: si+=len(subs)
        return catFilter

    def handlePreClose(self):
        if util.getSetting('back_opens_context',False):
            xbmc.executebuiltin('Action(ContextMenu)')
            return True

        if xbmc.getCondVisibility('Player.HasVideo'):
            if util.getSetting('fullscreen_on_exit',True):
                if util.getSetting('keep_epg_open',False):
                    self.fullscreenVideo()
                    return True
                self.mode = None
                self.window.close()
                self.fullscreenVideo()
                return False

        self.mode = None
        return False

    def doContextMenu(self,show_download=True):
        self.window.setProperty('covered','yes')
        try:
            self._doContextMenu(show_download=show_download)
        finally:
            if self.window: self.window.setProperty('covered','')

    def _doContextMenu(self,show_download=True):
        item = self.getSelectedProgramOrChannel()
        d = util.xbmcDialogSelect()
        if not self.search_key == '':
            return

        d.addItem('play_channel','Play Channel')
        d.addItem('search_event','Search by keyword...')
        d.addItem('favourite','Favourite')
        if show_download:
            if item._ssType == 'PROGRAM':
                if item.isAiring():
                    if self.player.canDownload(): d.addItem('download',u'Record:  [B][I]{0}[/I][/B]'.format(item.title))
                else:
                    d.addItem('schedule',u'Schedule:  [B][I]{0}[/I][/B]'.format(item.title))
                    if self.player.canDownload(): d.addItem('download',u'Record:  [B][I]{0}[/I][/B]'.format(item.channelParent.title))
            else:
                if self.player.canDownload(): d.addItem('download',u'Record:  [B][I]{0}[/I][/B]'.format(item.title))
        if self.player.isDownloading():
            d.addItem('stop_download','Stop Recording')
        if not DownloadRegistry().empty():
            d.addItem('view_recordings','View Recordings')
        d.addItem('changeQuality', 'Change Quality')
        d.addItem('changeView','Change View')
        d.addItem('settings','Settings')
        if (util.getSetting('back_opens_context',False) or util.getSetting('show_fullscreen_option',False)) and xbmc.getCondVisibility('Player.HasVideo'):
            d.addItem('fullscreen','Fullscreen Video')
        if util.getSetting('keep_epg_open',False) or util.getSetting('back_opens_context',False):
            d.addItem('exit','Exit')

        selection = d.getResult()
        if selection == None: return
        if selection == 'search_event':
            self.search()
        elif selection == 'download':
            self.record(item)
        elif selection == 'schedule':
            self.scheduleRecording(item)
        elif selection == 'stop_download':
            self.player.stopDownload()
        elif selection == 'view_recordings':
            self.viewRecordings()
        elif selection == 'cat':
            self.switch('CATS')
        elif selection == 'epg':
            self.switch('EPG')
        elif selection == 'panel':
            self.switch('PANEL')
        elif selection == 'play_channel':
            self.playChannel()
        elif selection == 'settings':
            self.showSettings()
        elif selection == 'favourite':
            self.favourite()
        elif selection == 'fullscreen':
            xbmc.executebuiltin('Action(FullScreen)')
        elif selection == 'modern' or selection == 'classic':
            self.changeTheme(selection)
        elif selection == 'changeView':
            self.changeView(selection)
        elif selection == 'changeQuality':
            self.changeQuality(selection)
        elif selection == 'exit':
            self.mode = None
            self.window.close()
            if util.getSetting('fullscreen_on_exit',True): self.fullscreenVideo()
    
    def changeQuality(self,quality):
        dialog = util.xbmcDialogSelect('Change Quality')
        dialog.addItem('hd','High Definition')
        dialog.addItem('ld','Low Definition')
        result = dialog.getResult()

        util.setSetting('high_def', result == 'hd')
        return

    def changeView(self,view):
        dialog = util.xbmcDialogSelect('Change View')
        dialog.addItem('cat','List')
        dialog.addItem('epg','EPG')
        if util.getSetting('theme') == 'true':
            dialog.addItem('panel','Panel')
        result = dialog.getResult()
        
        if result == 'cat':
            self.switch('CATS')
        elif result == 'epg':
            self.switch('EPG')
        elif result == 'panel':
            self.switch('PANEL')
        return

    def changeTheme(self,theme):
        self.theme = theme
        util.setSetting('theme',theme)
        xbmc.log(str(util.getSetting('last_mode')),2)
        xbmc.log(str(theme),2)
        if theme == 'classic' and util.getSetting('last_mode') == 'PANEL':
            util.setSetting('last_mode','CATS')
            self.mode = 'CATS'
        self.window.doClose()
        self.mode=None
        #xbmc.executebuiltin("xbmc.RunScript(script.smoothstreams-v3)")
        return

    def createFav(self,name='Default'):
        profile_file = os.path.join(util.PROFILE,'favourite')
        profile_name = os.path.join(util.PROFILE,name)
        default_profile = "show_all:true,show_30401:true,show_30402:true,show_30403:true,show_30404:true,show_30405:true,show_30406:true,show_30407:true,show_30408:true,show_30409:true,show_30410:true,show_30411:true,show_30412:true,show_30413:true,show_30414:true,show_30415:true,show_30416:true,show_30417:true,show_30418:true,show_30419:true,show_30420:true,show_30421:true"

        if not os.path.exists(profile_name):
            with open(profile_file,'a') as fav:
                fav.write(name + ',')

            with open(profile_name, 'w') as new_fav:
                new_fav.write(default_profile)
            util.notify('Favourite List', name + ' list created')
            if name == 'Default':
                util.setSetting('favourite',name)
            return
        if not name == 'Default':
            util.notify('Favourite List', name + ' list exists')

    def deleteFav(self, dialog=None):
        if not dialog:  return
        profile_file = os.path.join(util.PROFILE,'favourite')

        favList = self.listFav(dialog,1)
        for fav in favList:
            if not fav == 'Default':
                dialog.addItem(fav,fav)

        result = dialog.getResult()
        if result:
            if result == util.getSetting('favourite'):
                self.switchFav('Default')
            favList.remove(result)
            with open(profile_file,'w') as favFile:
                favFile.write(','.join(favList) + ',')
            del_profile = os.path.join(util.PROFILE, result)
            xbmc.log(str(del_profile),2)
            os.remove(del_profile)
            util.notify('Favourite List', result + ' list deleted')

    def listFav(self,dialog=None,getList=0):
        if not dialog:  return
        profile_file = os.path.join(util.PROFILE,'favourite')
        
        with open(profile_file,'r') as fp:
            favList = fp.read().split(',')[0:-1]
        
        if favList:
            if getList: return favList
            active_fav = util.getSetting('favourite')
            for fav in favList:
                if not fav: continue
                value = fav
                if fav == active_fav:   fav = '[COLOR orange][B]' + fav + '[/B][/COLOR]'
                
                dialog.addItem(value,fav)
        dialog.addItem('create_favourite','[COLOR blue]Create Favourite List[/COLOR]')
        dialog.addItem('delete_favourite','[COLOR red]Delete Favourite List[/COLOR]')
    
    def switchFav(self,result):
        default_profile = "show_all:true,show_30401:true,show_30402:true,show_30403:true,show_30404:true,show_30405:true,show_30406:true,show_30407:true,show_30408:true,show_30409:true,show_30410:true,show_30411:true,show_30412:true,show_30413:true,show_30414:true,show_30415:true,show_30416:true,show_30417:true,show_30418:true,show_30419:true,show_30420:true,show_30421:true"

        if not util.getSetting('favourite') == result:
            current_profile_data = ""
            current_profile_file = os.path.join(util.PROFILE,util.getSetting('favourite'))
            for set in default_profile.split(','):
                val = util.getSetting(set.split(':')[0])
                current_profile_data += set.split(':')[0] +":"+val + ","

            #Write existing settings to previous profile file
            with open(current_profile_file, 'w') as c_p_f:
                c_p_f.write(current_profile_data[0:-1])                    

            util.setSetting('favourite',result)
            current_profile_file = os.path.join(util.PROFILE,util.getSetting('favourite'))
            #Generate new setting from selected profile file
            with open(current_profile_file, 'r') as c_p_f:
                data = c_p_f.read()
            
            category = []
            for set in data.split(','):
                util.setSetting(set.split(':')[0],set.split(':')[1])
                xbmc.log(str(set),2)
                if set.split(':')[1] == 'true':
                    xbmc.log("in if...",2)
                    data = [d['name'] for d in self.window.categories if d['id'] == set.split(':')[0]]
                    xbmc.log(str(data),2)
                    if data:    category.append(data[0])
            xbmc.log(str(category),2)
            self.window.category=category
            #Enable new list
            util.notify('Favourite List', result + ' list enabled.')
            self.window.fillCategories()
            self.window.showList()
            
        else:
            util.notify('Favourite List', result + ' is already enabled.')
    def favourite(self):
        favList = []
        dialog = util.xbmcDialogSelect('Manage Favourite')
        self.listFav(dialog)
        result = dialog.getResult()
        
        if result == 'create_favourite':
            keyword = xbmcgui.Dialog().input('Enter Favourite List Name')
            if not keyword: return
            #Create fresh profile for favourite
            self.createFav(keyword)

        elif result == 'delete_favourite':
            deldialog = util.xbmcDialogSelect('Delete Favourite')
            self.deleteFav(deldialog)

        elif result:
            if xbmcgui.Dialog().yesno('Favourite List','Do you want to enable ' + result + ' profile?'):
                self.switchFav(result)

    def search(self):
        keyword = xbmcgui.Dialog().input('Enter search keyword')
        if not keyword:
            return
        self.search_key = keyword

        self.window_search = KodiListDialog('script-smoothstreams-category.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)
        self.window_search.doModal()
        self.window_search.onClosed()
        del self.window_search

        self.search_key = ''
        self.window_search = None

    
    def showSettings(self):
        gmtOffsetOld = util.getSetting('gmt_offset',0)
        old12HourTimes = util.getSetting('12_hour_times',False)
        oldLoginPass = (util.getSetting('service',0),util.getSetting('username'),util.getSetting('user_password'))
        state = self.window.getSettingsState()
        oldFULLEPG = util.getSetting('full_guide_switch',False)
        
        oldTheme = util.getSetting('theme',False)
        oldMode = util.getSetting('mode')

        util.openSettings()

        if oldLoginPass != (util.getSetting('service',0),util.getSetting('username'),util.getSetting('user_password')):
            self.player.resetTokens()

        self.setEPGLimits()
        settingsOffsetHours = util.getSetting('gmt_offset',0)
        if gmtOffsetOld != settingsOffsetHours or old12HourTimes != util.getSetting('12_hour_times',False):
            #self.setutcOffsetMinutes()
            #self.updateChannels()

            self.window.updateSettings(state)

        if oldFULLEPG != util.getSetting('full_guide_switch',False):
            self.window.updateEPG()

        if oldTheme != util.getSetting('theme',False):
            xbmc.log("Change Theme.....",2)
            self.mode=None
            self.window.close()
            xbmcgui.Dialog().ok("Restart SmoothStreams","Theme has been changed, please restart the addon to take effect.")
            return
        if oldMode != util.getSetting('mode'):
            xbmc.log("Change Mode.....",2)
            modes = {'List':'CATS','EPG':'EPG','Panel':'PANEL'}
            self.switch(modes[util.getSetting('mode')])
            return
        
    def getSelectedProgramOrChannel(self):
        return self.window.getSelectedProgram() or self.window.getSelectedChannel()

    def getCurrentProgramOrChannel(self):
        program = self.window.getSelectedProgram()
        if program and program.isAiring(): return program
        return self.window.getSelectedChannel()

    def record(self,item):
        self.player.download(item)

    def scheduleRecording(self,item):
        self.player.schedule(item)

    def checkRegistry(self,registry):
        key = util.getSetting('sort_recordings_alpha',False) and (lambda x: x.display) or (lambda x: x.ID)
        registry.cleanScheduled()
        return sorted([i for i in registry if i._udType != 'SCHEDULE_ITEM'],key=key,reverse=not util.getSetting('sort_recordings_alpha',False))

    def viewRecordings(self):
        with DownloadRegistry() as registry:
            result = True
            while result != None:
                dialog = util.xbmcDialogSelect('Select Recording')
                missing = False
                for item in self.checkRegistry(registry) + URLDownloader.scheduledItems():
                    if not item: continue
                    if item.exists():
                        rec = ''
                        if item.isDownloading(): rec = u'[COLOR FFFF0000]{0}[/COLOR] '.format(unichr(0x2022))
                        dialog.addItem(item,u'{0}{1}'.format(rec,item.display))
                    elif item._udType == 'SCHEDULE_ITEM':
                        dt = datetime.datetime.fromtimestamp(item.start)
                        if datetime.datetime.now().strftime('%j') == dt.strftime('%j'):
                            dd = dt.strftime(util.TIME_DISPLAY + ' (Today)')
                        else:
                            dd = dt.strftime(util.TIME_DISPLAY + '(%a)')
                        dialog.addItem(item,u'[COLOR FF9999FF]@[/COLOR] {1}:  [I]{0}[/I]'.format(item.display,dd))
                    else:
                        missing = True
                        dialog.addItem(item,u'([COLOR FFFF0000]MISSING[/COLOR]) {0}'.format(item.display))
                dialog.addItem('delete','[B][Delete Recordings][/B]')
                if missing:
                    dialog.addItem('remove_missing','[B][Remove Missing Entries][/B]')
                result = dialog.getResult()
                if result == None: return
                if result == 'delete':
                    self.deleteRecordings(registry)
                    continue
                elif result == 'remove_missing':
                    registry.removeMissing()
                    continue

                item = result
                if item.exists():
                    self.player.playRecording(item)
                    return
                elif item._udType == 'SCHEDULE_ITEM':
                    self.unScheduleItem(registry,item)
                else:
                    delete = xbmcgui.Dialog().yesno('Missing','The recording is missing for this entry.','','Would you like to delete this entry?','Keep','Delete')
                    if delete:
                        registry.remove(item)

    def deleteRecordings(self,registry):
        result = True
        while result != None:
            dialog = util.xbmcDialogSelect('Delete Recording')
            key = util.getSetting('sort_recordings_alpha',False) and (lambda x: x.display) or (lambda x: x.ID)
            for item in sorted(registry,key=key,reverse=not util.getSetting('sort_recordings_alpha',False)):
                if item.exists():
                    rec = ''
                    if item.isDownloading(): rec = u'[COLOR FFFF0000]{0}[/COLOR] '.format(unichr(0x2022))
                    dialog.addItem(item,u'Delete: {0}{1}'.format(rec,item.display))
                else:
                    dialog.addItem(item,u'Delete: ([COLOR FFFF0000]MISSING[/COLOR]) {0}'.format(item.display))
            dialog.addItem('delete_all','[B][Delete All][/B]')
            result = dialog.getResult()
            if result == None: return
            if result == 'delete_all':
                delete = xbmcgui.Dialog().yesno('Delete','This will PERMANENTLY remove ALL recording files.','','Are you really sure you want to do this?','Keep','DELETE!')
                if not delete: continue
                delete = xbmcgui.Dialog().yesno('Delete','LAST CHANCE TO CHANGE YOUR MIND!','','Do you really want to delete ALL recordings?','Keep','DELETE!')
                if not delete: continue
                return registry.deleteAll()
            delete = xbmcgui.Dialog().yesno('Delete','This will PERMANENTLY remove this recording file.','','Are you sure you would like to delete this recording?','Keep','Delete')
            if delete:
                registry.delete(result)

    def unScheduleItem(self,registry,item):
        delete = xbmcgui.Dialog().yesno('Delete','Are you sure you would like to remove','this scheduled recording?','','Keep','Remove')
        if delete:
            URLDownloader.unSchedule(item)
            registry.delete(item)

    def playChannel(self):
        channel = self.selectChannel()
        if not channel: return
        self.player.play(channel)

    def selectChannel(self):
        d = util.xbmcDialogSelect('Channels')
        for channel in self.channels:
            d.addItem(channel,channel['display-name'])
        return d.getResult()

    def startOfDay(self):
        return smoothstreams.timeutils.startOfDayLocalTimestamp()

    def timeInDay(self):
        return smoothstreams.timeutils.timeInDayLocalSeconds()/60

    def getHalfHour(self):
        tid = self.timeInDay()
        return tid - (tid % 30)

    def initDisplayOffset(self):
        timeInDay = self.timeInDay()

        self.displayOffset = (timeInDay - (timeInDay % 30))
        self.setEPGLimits()

    def setutcOffsetMinutes(self):
        settingsOffsetHours = util.getSetting('gmt_offset',0)
        if settingsOffsetHours:
            self.setutcOffsetMinutesFromSettings(settingsOffsetHours)
        else:
            smoothstreams.timeutils.setLocalTimezone()

    def setutcOffsetMinutesFromSettings(self, settingsOffsetHours):
        utcOffsetHalfHour = util.getSetting("gmt_offset_half",False)
        dst = util.getSetting("daylight_saving_time",False)

        offset = 0
        if settingsOffsetHours == 1:
            util.LOG("Timezone gmt0")
        elif settingsOffsetHours < 14:
            util.LOG("Timezone gmt+")
            offset = 60 * (settingsOffsetHours - 1)
        elif settingsOffsetHours > 13:
            util.LOG("Timezone gmt-")
            offset = -60 * (settingsOffsetHours - 13)

        if dst:
            util.LOG("Daylight saving time")
            offset += 60

        if utcOffsetHalfHour:
            util.LOG("gmt + 30 min")
            offset += 30

        smoothstreams.timeutils.setLocalTimezone(offset)

    def initChannels(self):
        sod = self.startOfDay()
        for channel in self.channels:
            for program in channel.get('programs',{}):
                program.update(sod)

    def getProgramByID(self,pid):
        for channel in self.channels:
            for program in channel.get('programs',{}):
                if pid == program.pid:
                    return program

    def activateOverlay(self):
        if not util.getSetting('fullscreen_overlay',False): return
        if util.getSetting('seek_protection',False):
            with util.KeymapOverride():
                overlay = SeekProtectionOverlayDialog('script-smoothstreams-overlay.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)
        else:
            overlay = OverlayDialog('script-smoothstreams-overlay.xml',util.ADDON.getAddonInfo('path'),self.theme,'720p',manager=self)

        overlay.doModal()
        del overlay

    def fullscreenVideo(self):
        if xbmc.getCondVisibility('Player.HasVideo'):
            xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            self.activateOverlay()

class ActionHandler(object):
    def __init__(self,callback):
        self.callback = callback
        self.event = threading.Event()
        self.event.clear()
        self.timer = None
        self.delay = 0.001

    def onAction(self,action):
        if self.timer: self.timer.cancel()
        if self.event.isSet(): return
        self.timer = threading.Timer(self.delay,self.doAction,args=[action])
        self.timer.start()

    def doAction(self,action):
        self.event.set()
        try:
            self.callback(action)
        finally:
            self.event.clear()

    def clear(self):
        if self.timer: self.timer.cancel()
        return self.event.isSet()

class FakeActionHandler(object):
    def __init__(self,callback):
        self.callback = callback

    def onAction(self,action):
        self.callback(action)

    def clear(self):
        return False

class BaseWindow(xbmcgui.WindowXML):
    def __init__(self,*args,**kwargs):
        self._closing = False
        self._winID = ''

    def onInit(self):
        self._winID = xbmcgui.getCurrentWindowId()

    def setProperty(self,key,value):
        if self._closing: return
        xbmcgui.Window(self._winID).setProperty(key,value)
        xbmcgui.WindowXMLDialog.setProperty(self,key,value)

    def doClose(self):
        self._closing = True
        self.close()

    def onClosed(self): pass

class BaseDialog(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self._closing = False
        self._winID = ''

    def onInit(self):
        self._winID = xbmcgui.getCurrentWindowDialogId()

    def setProperty(self,key,value):
        if self._closing: return
        xbmcgui.Window(self._winID).setProperty(key,value)
        xbmcgui.WindowXMLDialog.setProperty(self,key,value)

    def doClose(self):
        self._closing = True
        self.close()

    def onClosed(self): pass

#==============================================================================
# OverlayPlayer
#==============================================================================
class OverlayPlayer(xbmc.Player):
    def __init__(self,*args,**kwargs):
        self.overlay = kwargs.get('overlay')

    def onPlayBackEnded(self):
        self.overlay.close()

    def onPlayBackStopped(self):
        self.overlay.close()

#==============================================================================
# OverlayDialog
#==============================================================================
class OverlayDialog(BaseDialog):
    def __init__(self,*args,**kwargs):
        self.manager = kwargs.get('manager')
        self.player = OverlayPlayer(overlay=self)
        BaseDialog.__init__(self,*args,**kwargs)

    def onAction(self,action):
        #util.DEBUG_LOG(action.getId())
        try:
            if action == xbmcgui.ACTION_PREVIOUS_MENU:
                xbmc.executebuiltin('ActivateWindow(12005)')
                xbmc.executebuiltin('Action(PreviousMenu)')
            elif action == xbmcgui.ACTION_NAV_BACK:
                xbmc.executebuiltin('ActivateWindow(12005)')
                xbmc.executebuiltin('Action(Back)')
            elif action == xbmcgui.ACTION_BUILT_IN_FUNCTION:
                xbmc.executebuiltin('ActivateWindow(12901)')
            elif action == xbmcgui.ACTION_PAGE_UP:
                channel = self.manager.getChannel(str(self.manager.player.channelCurrentlyPlaying - 1))
                self.manager.player.playFromChannel(channel)
            elif action == xbmcgui.ACTION_PAGE_DOWN:
                channel = self.manager.getChannel(str(self.manager.player.channelCurrentlyPlaying + 1))
                self.manager.player.playFromChannel(channel)

            if self.manager.checkChannelEntry(action):
                return
        finally:
            BaseDialog.onAction(self,action)

class SeekProtectionOverlayDialog(OverlayDialog):
    def onAction(self,action):
        if action == xbmcgui.ACTION_MOVE_LEFT or action == xbmcgui.ACTION_MOVE_RIGHT or action == xbmcgui.ACTION_PREV_ITEM or action == xbmcgui.ACTION_NEXT_ITEM:
            return

        OverlayDialog.onAction(self,action)

#==============================================================================
# TimeIndicator
#==============================================================================
class TimeIndicator(object):
    def __init__(self,epg):
        self.epg = epg
        self.indicatorControl = self.epg.getControl(102)
        self.xLimit = self.epg.epgRight
#        self.lastHalfHourRight = 190 + (180 * 6)
        self.showing = False
        self.update()

    def hide(self):
        #Hide it if out of range
        self.showing = False
        self.indicatorControl.setPosition(-20,50)

    def move(self,pos):
        self.showing = True
        self.indicatorControl.setPosition(pos,50)

    def update(self,from_timer=True):
        timeInDay = smoothstreams.timeutils.timeInDayLocalSeconds()/60.0
        xPos = 190 + int(((timeInDay - self.epg.manager.displayOffset) * 6.0))

        if from_timer and self.showing and ((xPos >= self.xLimit and (xPos - self.xLimit < 12))): #Only advance if are just off the edge
            self.hide()
            return True

        if xPos < 181 or xPos > self.xLimit:
            self.hide()
            return False

#        if from_timer and xPos > self.lastHalfHourRight and self.showing:
#            self.move(xPos)
#            return True

        self.move(xPos)

#==============================================================================
# KodiEPGDialog
#==============================================================================
class KodiEPGDialog(BaseWindow,util.CronReceiver):
    def __init__(self,*args,**kwargs):
        self.manager = kwargs['manager']
        
        self.initSettings()
        self._started = False
        BaseWindow.__init__(self,*args,**kwargs)

    @util.busyDialog
    def initSettings(self,flag=1):
        self.manager.schedule = smoothstreams.Schedule()

        data = self.manager.schedule.epg(self.manager.startOfDay())
        self.manager.channels = data

        self.schedule = self.manager.schedule
        self.player = self.manager.player
        if flag:
            self.selectionTime = 0
            self.selectionPos = -1
            self.epg = None
        if util.getSetting('key_repeat_control',False):
            self.actionHandler = ActionHandler(self._onAction)
            util.DEBUG_LOG('Key-repeat throttling: ENABLED')
        else:
            self.actionHandler = FakeActionHandler(self._onAction)
            util.DEBUG_LOG('Key-repeat throttling: DISABLED')

        if util.getSetting('full_guide_switch',True):
            self.actionHandler = ActionHandler(self._onAction)
        self.wholePageLR = util.getSetting('scroll_lr_one_page',False)

    def onInit(self):
        BaseWindow.onInit(self)
        if self._started: return
        self.setWindowProperties()
        self._started = True
        self.setupEPG()
        self.timeIndicator = TimeIndicator(self) #Must be created after setupEPG()
#        self.epg.setHeight(408) #This doesn't work
        self.setProperty('selection_time','0')
#        print 'x:{0} y:{1} w:{2} h:{3}'.format(self.epg.getX(),self.epg.getY(),self.epg.getWidth(),self.epg.getHeight())
        self.initChannels()
        self.updateEPG()
        self.updateSelection(self.selectionTime)
        #self.showTweet()
        self.manager.cron.registerReceiver(self)

    def setWindowProperties(self):
        #self.setProperty('version','v{0}'.format(util.ADDON.getAddonInfo('version')))
        self.setProperty('hide_video_preview', not util.getSetting('show_video_preview',True) and '1' or '')

    '''def showTweet(self):
        if not util.getSetting('show_tweets',False): return
        import twitter
        sstwit = twitter.SSTwitterFeed()
        tweet = sstwit.getLatestTweet(True)
        if tweet:
            self.setProperty('message',tweet)
            #xbmcgui.Dialog().ok('News',tweet)'''

    def getSettingsState(self):
        return (    util.getSetting('12_hour_times',False),
                    util.getSetting('gmt_offset',0),
                    util.getSetting('schedule_plus_limiter',3),
                    util.getSetting('schedule_minus_limiter',2)
        )

    def updateSettings(self,state):
        self.initSettings(0)
        self.setWindowProperties()
        if state != self.getSettingsState():
            self.manager.setEPGLimits()
            self.updateEPG()
            self.updateSelection(self.selectionTime)

    def setupEPG(self):
        if not self.epg: self.epg = self.getControl(101)
        self.epgLeft = self.epg.getX() + 190
        self.epgRight = min((self.epg.getX()  + self.epg.getWidth() - 1),1280)
        self.epgTop = self.epg.getY()
        self.epgBottom = min(self.epg.getY()  + self.epg.getHeight(),720)

    def initChannels(self):
        items = []
        for channel in self.manager.channels:
            item = xbmcgui.ListItem(channel['display-name'],str(channel['ID']),iconImage=channel['logo'])
            items.append(item)

        self.epg.reset()
        self.epg.addItems(items)
        self.setFocusId(101)

    def updateEPG(self):
        self.timeIndicator.update()
        gridRange = range(-30,210,15)
        epgStart = -30 + self.manager.displayOffset
        epgEnd = 210 + self.manager.displayOffset

        for idx in range(len(self.manager.channels)):
            item = self.epg.getListItem(idx)
            programs = self.manager.channels[idx].get('programs',[])
            shown = {}
            
            categories = self.manager.createCategoryFilter()
            for program in programs:
                start = program.epg.start
                stop = program.epg.stop
                duration = program.epg.duration
                end = start + duration
                old = False
                
                #Temp fix for :15/:45 start or end of any program
                
                '''if start % 10 != 0 or stop % 10 != 0:
                    start += 15
                if duration % 10 != 0:
                    duration += 15'''

                #Fix for programs not starting at either 0/15/30/45
                if start % 60 != 0 or start % 60 != 15 or start % 60 != 30 or start % 60 != 45:
                    if start % 60 > 0 and start % 60 <= 7:
                        start -= start % 60
                    elif start % 60 > 7 and start % 60 < 15:
                        start += 15 - (start % 60)
                    elif start % 60 > 15 and start % 60 <= 22:
                        start -= (start % 60) - 15
                    elif start % 60 > 22 and start % 60 < 30:
                        start += 30 - (start % 60)
                    elif start % 60 > 30 and start % 60 <= 37:
                        start -= (start % 60) - 30
                    elif start % 60 > 37 and start % 60 < 45:
                        start += 45 - (start % 60)
                    elif start % 60 > 45 and start % 60 <= 52:
                        start -= (start % 60) - 45
                    elif start % 60 > 52 and start % 60 < 60:
                        start += 60 - (start % 60)
                
                if (start >= self.manager.lowerLimit or stop > self.manager.lowerLimit) and start < self.manager.upperLimit:

                    gridTime = start - self.manager.displayOffset
                    
                    if start >= epgStart and start < epgEnd:
                        shown[gridTime] = True
                        item.setProperty('Program_{0}_Duration'.format(gridTime),str(duration))
                        item.setProperty('Program_{0}_Label'.format(gridTime),program.title)
                    elif (end >= epgStart and end < epgEnd) or (start < epgStart and end > epgStart):
                        duration -= (-30 - gridTime)
                        if not duration: continue
                        gridTime = -30
                        shown[gridTime] = True
                        item.setProperty('Program_{0}_Duration'.format(gridTime),str(duration))
                        item.setProperty('Program_{0}_Label'.format(gridTime),program.title)

                    if gridTime in shown:
                        item.setProperty('Program_{0}_Color'.format(gridTime),program.epg.colorGIF)
            #Clear properties that we didn't set
            for s in gridRange:
                if not s in shown:
                    item.setProperty('Program_{0}_Duration'.format(s),'')
                    item.setProperty('Program_{0}_Label'.format(s),'')
        self.updateEPGTimes(gridRange)

    def updateEPGTimes(self,gridRange):
        nowDT = smoothstreams.timeutils.nowLocal()
        for s in gridRange:
            dt = datetime.datetime.fromtimestamp(self.manager.startOfDay() + smoothstreams.timeutils.TIMEZONE_OFFSET + ((self.manager.displayOffset + s) * 60))

            if dt.day != nowDT.day:
                timeDisp = datetime.datetime.strftime(dt,'%a {0}'.format(util.TIME_DISPLAY))
            else:
                timeDisp = datetime.datetime.strftime(dt,util.TIME_DISPLAY)

            if dt < nowDT and smoothstreams.timeutils.timedelta_total_seconds(nowDT - dt) > 1800:
                timeDisp = ' [COLOR FF888888]{0}[/COLOR]'.format(timeDisp)

            self.setProperty('Time_{0}'.format(s),timeDisp)

    def tick(self):
        if self.timeIndicator.update(True) and util.getSetting('auto_advance',True):
            self.nextItem()
            self.updateSelection(self.selectionTime)

    def halfHour(self):
        util.DEBUG_LOG('EPG: New half hour')
        self.manager.reloadChannels()
        self.updateSelection(self.selectionTime)

    def day(self):
        util.DEBUG_LOG('EPG: New day')
        self.manager.reloadChannels()
        if util.getSetting('auto_advance',True) and self.timeIndicator.showing:
            util.DEBUG_LOG('EPG: Auto advance: Day change - resetting displayOffset')
            self.manager.initDisplayOffset()
            # self.manager.displayOffset -= 150 #So time indicator is still on the last half hour
        self.updateEPG()
        self.updateSelection(self.selectionTime)
        return True

    def onClick(self, controlID):
        util.DEBUG_LOG('Clicked: {0}'.format(controlID))
        if controlID == 101:
            self.epgClicked()
        elif controlID == 110:
            self.prevItem()
        elif controlID == 111:
            self.nextItem()

    def onAction(self,action):
        try:
            #print action.getId()
            if action == xbmcgui.ACTION_MOVE_RIGHT:
                return self.actionHandler.onAction(action)
            elif action == xbmcgui.ACTION_MOVE_LEFT:
                return self.actionHandler.onAction(action)

            if self.actionHandler.clear(): return

            if action == xbmcgui.ACTION_MOVE_UP or action == xbmcgui.ACTION_MOVE_DOWN:
                self.updateInfo()
            elif action == xbmcgui.ACTION_PAGE_UP or action == xbmcgui.ACTION_PAGE_DOWN:
                self.updateInfo()
            elif action == xbmcgui.ACTION_CONTEXT_MENU:
                self.manager.doContextMenu()
            elif action == xbmcgui.ACTION_PREVIOUS_MENU or action == xbmcgui.ACTION_NAV_BACK:
                if self.manager.handlePreClose(): return
            elif action == xbmcgui.ACTION_RECORD:
                self.manager.record()
            #elif action == xbmcgui.ACTION_SHOW_GUI:
            #    if xbmc.getCondVisibility('Player.HasVideo'):
            #        self.activateOverlay()

            if self.manager.checkChannelEntry(action):
                return

            self.getMouseHover(action)
        except Exception as e:
            util.ERROR(str(e))
            BaseWindow.onAction(self,action)
            return
        BaseWindow.onAction(self,action)

    def _onAction(self,action):
        '''if action == xbmcgui.ACTION_MOVE_RIGHT:
            if not self.getSelectedProgram():
                self.moveRight()
                self.updateInfo()
            else:
                temp = self.getSelectedProgram()
                while self.getSelectedProgram():
                    self.moveRight()
                    if temp != self.getSelectedProgram():
                        break
                self.updateInfo()
                    
        elif action == xbmcgui.ACTION_MOVE_LEFT:
            if not self.getSelectedProgram():
                self.moveLeft()
                self.updateInfo()
            else:
                temp = self.getSelectedProgram()
                while self.getSelectedProgram():
                    self.moveLeft()
                    self.updateInfo()
                    if temp != self.getSelectedProgram():
                        break'''
        if action == xbmcgui.ACTION_MOVE_RIGHT:
            self.moveRight()
            #self.updateInfo()
        elif action == xbmcgui.ACTION_MOVE_LEFT:
            self.moveLeft()
            #self.updateInfo()

    def getMouseHover(self,action):
        x = action.getAmount1()
        y = action.getAmount2()
        if y < self.epgTop or x < self.epgLeft or y > self.epgBottom or x > self.epgRight : return
        elif x < 371: sel = 0
        elif x < 551: sel = 30
        elif x < 731: sel = 60
        elif x < 911: sel = 90
        elif x < 1091: sel = 120
        elif x < 1281: sel = 150
        pos = self.epg.getSelectedPosition()
        if sel == self.selectionTime and pos == self.selectionPos: return
        self.selectionTime = sel
        self.selectionPos = pos
        self.updateSelection(sel)

    def updateSelection(self,selection):
        #print('--- update selection routine ---')
        #print('selection requested:', str(selection))
        self.setProperty('selection_time',str(selection))
        offset = smoothstreams.timeutils.TIMEZONE_OFFSET
        todayStr = datetime.datetime.strftime(datetime.datetime.fromtimestamp(self.manager.startOfDay() + offset + ((self.manager.displayOffset + self.selectionTime) * 60)),'%a %d')
        self.setProperty('today',todayStr)
        self.updateInfo()

    def updateInfo(self):
        p = self.getSelectedProgram()
        if p:
            self.setProperty('program_title',p.title)
            self.setProperty('program_description',p.description)
            self.setProperty('program_times',p.epg.timeDisplay)
            self.setProperty('program_times1',p.epg.timeDisplay.split('(')[0])
            self.setProperty('program_duration',p.epg.timeDisplay.split('(')[1][0:-1])
            
            self.setProperty('program_quality',p.epg.quality)
            xbmcSelect, ver = self.getVersions(p)
            self.setProperty('program_versions','[CR]'.join(ver))
            self.setProperty('program_category',p.category)
            self.setProperty('program_flag','flags/{0}.png'.format(p.language))
        else:
            self.setProperty('program_title','')
            self.setProperty('program_description','')
            self.setProperty('program_times','')
            self.setProperty('program_times1','')
            self.setProperty('program_duration','')
            self.setProperty('program_quality','')
            self.setProperty('program_versions','')
            self.setProperty('program_category','')
            self.setProperty('program_flag','')

    def nextItem(self):
        self.selectionTime = 0
        self.manager.displayOffset+=150
        #self.manager.displayOffset+=self.selectionTime
        #if self.selectionTime > 150:
        #    self.selectionTime = 0
        #    self.manager.displayOffset+=150
        #else:
        #    print('inside upper limit')
        #    self.manager.displayOffset+=self.selectionTime
        #if self.manager.displayOffset + 150 >= self.manager.upperLimit: return
        #if self.wholePageLR:
        #    self.manager.displayOffset+=self.selectionTime
        #    self.selectionTime = 0
        #else:
        #    self.manager.displayOffset+=30
        self.updateEPG()

    def prevItem(self):
        self.selectionTime = 150
        self.manager.displayOffset-=150
        #if self.manager.displayOffset <= self.manager.lowerLimit: return
        #if self.wholePageLR:
        #    self.manager.displayOffset-=180
        #    self.selectionTime = 150
        #else:
        #    self.manager.displayOffset-=30
        self.updateEPG()

    def moveRight(self):
        move = 0
        try:
            program,grid = self.getSelectedProgram1()
            if program:
                #print('selected program', program.title)
                duration = program.duration/60
                #print('duration', str(duration))
                selection = self.getProperty('selection_time')
                #print('selection', str(selection))
                #print('epg start', str(program.epg.start))
                epg_end = program.epg.start + duration
                #print('epg end', str(epg_end))
                #print('display offset', str(self.manager.displayOffset))
                if (self.manager.displayOffset > program.epg.start):
                    #print('not the beginning of this show! getting remaining to move:')
                    move = duration - (self.manager.displayOffset - program.epg.start)
                elif ((program.epg.start - self.manager.displayOffset) != int(selection)):
                    #print('in the middle?')
                    move = duration - int(selection)
                else:
                    move = duration
        except:
            pass
        self.selectionTime += move if move > 0 else 30
        #print('move', str(move))
        #print('new selection time calculated', str(self.selectionTime))
        if self.selectionTime >= 150:
            self.selectionTime = 0
            self.nextItem()
        self.updateSelection(self.selectionTime)

    def moveLeft(self):
        move = 0
        try:
            program,grid = self.getSelectedProgram1()
            if program:
                #print('selected program', program.title)
                duration = program.duration/60
                #print('duration', str(duration))
                selection = self.getProperty('selection_time')
                #print('selection', str(selection))
                #print('epg start', str(program.epg.start))
                epg_end = program.epg.start + duration
                #print('epg end', str(epg_end))
                #print('display offset', str(self.manager.displayOffset))
                if (self.manager.displayOffset > program.epg.start):
                    #print('not the beginning of this show! getting remaining to move:')
                    move = int(selection) + (self.manager.displayOffset - program.epg.start)
                elif ((program.epg.start - self.manager.displayOffset) != int(selection)):
                    #print('in the middle?')
                    move = int(selection) - duration + 30
                    move = int(selection) - (program.epg.start - self.manager.displayOffset) + 30
            #if program:
            #    duration = program.duration/60
            #    selection_time = self.getProperty('selection_time')
            #    if duration > 30:
            #        if grid == int(selection_time):
            #            move = 30
            #        elif grid < int(selection_time):
            #            move = int(selection_time) - grid + 30
        except:
            pass
        self.selectionTime -= move if move > 0 else 30
        #print('move', str(move))
        #print('new selection time calculated', str(self.selectionTime))
        if self.selectionTime < 0:
            #print('selectionTime < 0 - update to 0 and prev page')
            self.selectionTime = 0
            self.prevItem()
        self.updateSelection(self.selectionTime)

    def getVersions(self,program):

        data = self.schedule.readProgramData()['data']
        channel = []
        flag = 0

        if program.parrentID == '0':
            for key,d in data.iteritems():
                if not isinstance(d['events'],list):
                    for key,e in d['events'].iteritems():
                        if e['parent_id'] == program.eventID:
                            channel.append(e)
                        if key == program.eventID and flag == 0:
                            flag = 1
                            channel.append(e)
            
        else:
            for key,d in data.iteritems():
                if not isinstance(d['events'],list):
                    for key,e in d['events'].iteritems():
                        if e['parent_id'] == program.parrentID:
                            channel.append(e)
                        if key == program.parrentID and flag == 0:
                            flag = 1
                            channel.append(e)

        def getKey(item):
            return int(item['channel'])
        schannel = sorted(channel, key=getKey)

        d = util.xbmcDialogSelect()
        ver = []
        for v in schannel:
            ch = data[v['channel']]['number']
            if len(ch) == 1: ch = '0' + str(ch)
            version = ch + " ( " + v['quality'] + " / " + v['language'].upper() + " )"
            ver.append(version)
            d.addItem(ch,version)
        
        #Here d is xbmcSelect options and ver is versions in python list
        return d, ver

    def epgClicked(self):
        program = self.getSelectedProgram()
        if not program:
            channel = self.getSelectedChannel()
            self.player.play(channel)
            return
        
        d, ver = self.getVersions(program)

        if len(ver) > 1:
            version = d.getResult()
            if not version:
                return
        else:
            #if only one version stream availalbe then do not pop up selection just get version and pass it to player.
            version = ver[0].split(' (')[0]
        channel = self.manager.getChannel(version)
        self.player.play(channel)
        return
        '''if util.getSetting('ask_version', True) and len(program.versions) > 1:
            d = util.xbmcDialogSelect()
            for v in program.versions:
                d.addItem(v, v)
            version = d.getResult()
            if not version:
                return

            channel = self.manager.getChannel(version.split(' ', 1)[0].lstrip('0'))
            if not channel:
                util.DEBUG_LOG('Could not find channel for version!')
                return

            self.player.play(channel)
            return

        self.player.play(program)'''

    def getSelectedChannel(self):
        idx = self.epg.getSelectedPosition()
        return self.manager.channels[idx]

    def getSelectedProgram1(self):
        idx = self.epg.getSelectedPosition()
        if not self.manager.channels: return None
        channel = self.manager.channels[idx]
        if not 'programs' in channel: return None
        for program in channel['programs']:
            gridTime = program.epg.start - self.manager.displayOffset
            if self.selectionTime >= gridTime and self.selectionTime < gridTime + program.epg.duration:
                return program,gridTime
        return None,None

    def getSelectedProgram(self):
        idx = self.epg.getSelectedPosition()
        if not self.manager.channels: return None
        channel = self.manager.channels[idx]
        if not 'programs' in channel: return None
        for program in channel['programs']:
            gridTime = program.epg.start - self.manager.displayOffset
            if self.selectionTime >= gridTime and self.selectionTime < gridTime + program.epg.duration:
                return program
        return None

    def onClosed(self):
        self.manager.cron.cancelReceiver(self)

#==============================================================================
# KodiListDialog
#==============================================================================
class KodiListDialog(BaseWindow,util.CronReceiver):
    def __init__(self,*args,**kwargs):
        self.manager = kwargs['manager']
        self.manager.schedule1 = smoothstreams.Schedule(True)
        self.manager.channels1 = self.manager.schedule1.epg(self.manager.startOfDay())
        
        self.categories = self.manager.schedule1.categories()
        self.category = []
        self.started = False
        self.lastHalfHour = 0
        self.progressItems = []
        self.lastHalfHour = self.manager.getHalfHour()
        BaseWindow.__init__(self,*args,**kwargs)

    def onInit(self):
        BaseWindow.onInit(self)
        if self.started: return
        self.setWindowProperties()
        self.started = True
        self.categoryList = self.getControl(101)
        self.programsList = kodigui.ManagedControlList(self,201,11)
        self.fillCategories()
        self.setProperty('category','ALL')
        if not self.manager.search_key == '':
            self.setProperty('category','Search Results for: ' + str(self.manager.search_key))
        self.showList()
        self.setFocusId(200)
        self.manager.cron.registerReceiver(self)

    def setWindowProperties(self):
        self.setProperty('version','v{0}'.format(util.ADDON.getAddonInfo('version')))
        self.setProperty('hide_video_preview', not (util.getSetting('show_video_preview',True) and not util.getSetting('disable_list_view_preview',False)) and '1' or '')

    def tick(self):
        self.updateProgressBars()

    def halfHour(self):
        util.DEBUG_LOG('List view: New half hour')
        self.updateProgramItems()
        return True


    def day(self):
        util.DEBUG_LOG('List view: New day')
        self.manager.reloadChannels()
        self.showPrograms()
        return True

    def updateProgressBars(self):
        timeInDay = self.manager.timeInDay()
        for item in self.progressItems:
            program = item.dataSource
            prog = ((timeInDay - program.epg.start)/float(program.epg.duration))*100
            prog = int(prog - (prog % 5))
            if util.getSetting('last_mode') == 'PANEL':
                tex = 'progress_line/{0}.png'.format(prog)
            else:
                tex = 'progress_circle/{0}.png'.format(prog)
            item.setProperty('playing',tex)

    def updateProgramItems(self):
        util.DEBUG_LOG('List view: New half hour')
        self.progressItems = []
        startOfDay = smoothstreams.timeutils.startOfDayLocalTimestamp()
        timeInDay = self.manager.timeInDay()
        oldItems = []
        items = []

        selected = self.programsList.getSelectedItem()
        onCurrent = False
        for idx in self.programsList.getViewRange():
            if not self.programsList[idx].getProperty('old'):
                onCurrent = True
                break

        oldViewPosition = self.programsList.getViewPosition()

        for i in range(self.programsList.size()):
            item = self.programsList[i]
            pid = item.getProperty('pid')
            program = self.manager.getProgramByID(pid)
            self.updateItemData(item,program,startOfDay,timeInDay)
            if item.getProperty('old'):
                oldItems.append(item)
            else:
                items.append(item)

        oldItems.sort(key=lambda x: int(x.getProperty('sort')))
        self.programsList.replaceItems(oldItems + items)

        if util.getSetting('auto_advance',True) and onCurrent:
            selected = self.programsList.getSelectedItem()
            if selected and selected.getProperty('old'):
                pos = selected.pos() + 1
                while self.programsList.positionIsValid(pos):
                    item = self.programsList[pos]
                    if not item.getProperty('old'):
                        self.programsList.selectItem(item.pos())
                        xbmc.sleep(100) #Allow Kodi to actually update the position
                        viewPosition = self.programsList.getViewPosition()

                        if viewPosition > oldViewPosition:
                            diff = viewPosition - oldViewPosition
                            self.programsList.shiftView(diff,True)

                        break
                    pos += 1
                else:
                    self.programsList.selectItem(self.programsList.size()-1)

    def onAction(self,action):
        try:
            if action == xbmcgui.ACTION_CONTEXT_MENU:
                self.manager.doContextMenu(show_download=self.getFocusId() == 201)
            elif action == xbmcgui.ACTION_PREVIOUS_MENU or action == xbmcgui.ACTION_NAV_BACK:
                if self.manager.handlePreClose(): return
            elif action == xbmcgui.ACTION_RECORD:
                self.manager.record()

            if self.manager.checkChannelEntry(action):
                return
        except Exception as e: 
            util.ERROR(str(e))
            BaseWindow.onAction(self,action)
            return
        BaseWindow.onAction(self,action)

    def onClick(self,controlID):
        if controlID == 101:
            self.categorySelected()
        elif controlID == 201:
            self.programSelected()

    def categorySelected(self):
        item = self.categoryList.getSelectedItem()
        name = item.getProperty('category')
        if name == "ALL":
            for d in range(1,len(self.categories)):
                i = self.categoryList.getListItem(d)
                if item.getProperty('selected') == 'true':
                    i.setProperty('selected','false')
                    util.setSetting(i.getProperty('id'),'false')
                else:
                    i.setProperty('selected','true')
                    if i.getProperty('category') not in self.category:  self.category.append(i.getProperty('category'))
                    util.setSetting(i.getProperty('id'),'true')
            
            if item.getProperty('selected') == 'false':
                item.setProperty('selected','true')
                util.setSetting(item.getProperty('id'),'true')
                if not 'ALL' in self.category:  self.category.append('ALL')
            else:
                item.setProperty('selected','false')
                util.setSetting(item.getProperty('id'),'false')
                self.category = []
            self.showPrograms()
            return

        stat = item.getProperty('selected')
        
        if str(stat) == 'false' or stat == '':
            item.setProperty('selected','true')
            util.setSetting(item.getProperty('id'),'true')
        else:
            item.setProperty('selected','false')
            util.setSetting(item.getProperty('id'),'false')

        for d in range(0,len(self.categories)):
            i = self.categoryList.getListItem(d)
            cat = i.getProperty('category')
            if i.getProperty('selected') == 'true':
                if cat not in self.category: self.category.append(cat)
            else:
                if cat in self.category: self.category.remove(cat)

        if not self.categoryCount == len(self.category):
            i = self.categoryList.getListItem(0)
            i.setProperty('selected','false')
            util.setSetting(i.getProperty('id'),'false')
            if "ALL" in self.category: self.category.remove("ALL")

        if self.categoryCount - 1 == len(self.category):
            i = self.categoryList.getListItem(0)
            i.setProperty('selected','true')
            util.setSetting(i.getProperty('id'),'true')
            if "ALL" not in self.category: self.category.append("ALL")

        self.showPrograms()

    def programSelected(self):
        item = self.programsList.getSelectedItem()
        if not item: return
        self.manager.player.play(item.dataSource)

    def showPrograms(self):
        self.showList()
        return

    def getGifPath(self,c):
        hexColor = smoothstreams.schedule.SPORTS_TABLE.get(c.lower(),{}).get('color','808080')
        return util.makeColorGif(hexColor,os.path.join(util.COLOR_GIF_PATH,'{0}.gif'.format(hexColor)))

    def fillCategories(self):
        items = []
        '''item = xbmcgui.ListItem('All')
        item.setProperty('color', util.makeColorGif('FFFFFFFF',os.path.join(util.COLOR_GIF_PATH,'{0}.gif'.format('FFFFFFFF'))))
        item.setProperty('category','ALL')
        self.category.append("ALL")
        item.setProperty('selected','true')
        items.append(item)'''
        self.categories = [
            {"id":"show_all","name":"ALL"},
            {"id":"show_30401","name":"American Football"},
            {"id":"show_30404","name":"Baseball"},
            {"id":"show_30405","name":"Basketball"},
            {"id":"show_30408","name":"Boxing + MMA"},
            {"id":"show_30409","name":"Cricket"},
            {"id":"show_30410","name":"Golf"},
            {"id":"show_30411","name":"Ice Hockey"},
            {"id":"show_30412","name":"Motor Sports"},
            {"id":"show_30415","name":"Olympics"},
            {"id":"show_30416","name":"Other Sports"},
            {"id":"show_30417","name":"Rugby"},
            {"id":"show_30418","name":"Tennis"},
            {"id":"show_30419","name":"TV Shows"},
            {"id":"show_30420","name":"World Football"},
            {"id":"show_30421","name":"Wrestling"}
        ] 
        self.catsub = { 'American Football':('- NCAAF','- NFL'),
                    'Basketball':('- NBA','- NCAAB'),
                    'Motor Sports':('- Formula 1','- Nascar'),
                    'TV Shows':('- General TV'),
                    }

        for c in self.categories:
            item = xbmcgui.ListItem(c['name'])
            item.setProperty('category',c['name'])
            stat = util.getSetting(c['id'],bool)
            if stat == 'true':
                self.category.append(c['name'])
            item.setProperty('selected',stat)
            item.setProperty('id',c['id'])
            item.setProperty('color',self.getGifPath(c['name']))
            items.append(item)
        self.categoryList.reset()
        self.categoryList.addItems(items)
        self.categoryCount = len(items)

    def refresh(self):
        pos = self.programsList.getSelectedPosition()
        oldSize = self.programsList.size()
        if not self.showList(): return
        size = self.programsList.size()
        if size != oldSize: return
        if size and pos < size: self.programsList.selectItem(pos)

    def updateItemData(self,item,program,startOfDay,timeInDay):
        start = program.epg.start
        stop = program.epg.stop
        dt = datetime.datetime.fromtimestamp(startOfDay + (start*60),tz=smoothstreams.timeutils.LOCAL_TIMEZONE)
        if start >= 0 and start < 1440:
            timeDisp = datetime.datetime.strftime(dt,util.TIME_DISPLAY)
        else:
            timeDisp = datetime.datetime.strftime(dt,'%a {0}'.format(util.TIME_DISPLAY))
        item.setLabel2(timeDisp)
        sort = (((start * 1440) + stop ) * 100) + program.channel
        item.setProperty('old','')
        if stop <= timeInDay:
            item.setProperty('old','old')
            item.setProperty('playing','')
        elif start <= timeInDay:
            prog = ((timeInDay - start)/float(program.epg.duration))*100
            prog = int(prog - (prog % 5))
            if util.getSetting('last_mode') == 'PANEL':
                tex = 'progress_line/{0}.png'.format(prog)
            else:
                tex = 'progress_circle/{0}.png'.format(prog)
            item.setProperty('playing',tex)
            self.progressItems.append(item)
        item.setProperty('sort',str(sort))

    def showList(self):
        categories = self.category
        if self.manager.search_key == '':
            self.setProperty('category','ALL')
            if not self.categoryCount == len(categories):
                self.setProperty('category','FILTERED')
        oldItems = []
        items = []
        self.progressItems = []
        startOfDay = smoothstreams.timeutils.startOfDayLocalTimestamp()
        timeInDay = self.manager.timeInDay()
        for channel in self.manager.channels1:
            if not 'programs' in channel: continue
            for program in channel['programs']:
                if not self.manager.search_key == '' and not self.manager.search_key.lower() in program.title.lower():
                    continue
                start = program.epg.start
                stop = program.epg.stop
                old = False
                if (categories is None or program.category in categories or program.subcategory in  categories) and (start >= self.manager.lowerLimit or stop > self.manager.lowerLimit) and start < self.manager.upperLimit:
                    dt = datetime.datetime.fromtimestamp(startOfDay + (start*60),tz=smoothstreams.timeutils.LOCAL_TIMEZONE)
                    if start >= 0 and start < 1440:
                        timeDisp = datetime.datetime.strftime(dt,util.TIME_DISPLAY)
                    else:
                        timeDisp = datetime.datetime.strftime(dt,'%a {0}'.format(util.TIME_DISPLAY))

                    if util.getSetting('12_hour_times') == 'true':
                        if len(str(timeDisp).split(' ')) > 2:
                            t = str(timeDisp).split(' ',1)[1]
                            temp = dt.strftime('%b %d')
                            disp_time = str(temp) + ', ' + str(t)
                        else:
                            t = str(timeDisp)
                            disp_time = 'Today, ' + t
                    else:
                        if len(str(timeDisp).split(' ')) > 1:
                            t = str(timeDisp).split(' ',1)[1]
                            temp = dt.strftime('%b %d')
                            disp_time = str(temp) + ', ' + str(t)
                        else:
                            t = str(timeDisp)
                            disp_time = 'Today, ' + t
                    item = kodigui.ManagedListItem(program.title,disp_time,iconImage=channel['old_logo'],data_source=program)
                    sort = (((start * 1440) + stop ) * 100) + program.channel
                    if stop <= timeInDay:
                        item.setProperty('old','old')
                        old = True
                    elif start <= timeInDay:
                        prog = ((timeInDay - start)/float(program.epg.duration))*100
                        prog = int(prog - (prog % 5))
                        if util.getSetting('last_mode') == 'PANEL':
                            tex = 'progress_line/{0}.png'.format(prog)
                        else:
                            tex = 'progress_circle/{0}.png'.format(prog)
                        item.setProperty('playing',tex)
                        self.progressItems.append(item)
                    item.setProperty('sort',str(sort))
                    item.setProperty('channel',str(channel['ID']))
                    item.setProperty('duration',program.displayDuration)
                    item.setProperty('quality',program.epg.quality)
                    item.setProperty('color',program.epg.colorGIF)
                    item.setProperty('pid',program.pid)
                    item.setProperty('flag','flags/{0}.png'.format(program.language))
                    if old:
                        oldItems.append(item)
                    else:
                        items.append(item)
        items.sort(key=lambda x: int(x.getProperty('sort')))
        oldItems.sort(key=lambda x: int(x.getProperty('sort')))
        items = oldItems + items
        self.programsList.reset()
        if not items: return False
        self.programsList.addItems(items)

        self.programsList.selectItem(len(items)-1)

        for i in range(len(items)):
            if not items[i].getProperty('old'):
                self.programsList.selectItem(i)
                break
        return True

    def getSelectedChannel(self):
        item = self.programsList.getSelectedItem()
        if not item: return None
        return item.dataSource.channelParent

    def getSelectedProgram(self):
        item = self.programsList.getSelectedItem()
        if not item: return None
        return item.dataSource

    def initSettings(self): pass

    def getSettingsState(self):
        state = [   util.getSetting('12_hour_times',False),
                    util.getSetting('gmt_offset',0),
                    util.getSetting('schedule_plus_limiter',3),
                    util.getSetting('schedule_minus_limiter',2),
                    util.getSetting('show_all',True)
        ]

        for i in range(30401,30422):
            state.append(util.getSetting('show_{0}'.format(i),True))
        return state

    def updateSettings(self,state):
        self.fillCategories()
        self.setWindowProperties()
        if state != self.getSettingsState():
            self.refresh()

    def onClosed(self):
        self.manager.cron.cancelReceiver(self)

class KodiChannelEntry(BaseDialog):
    def __init__(self,*args,**kwargs):
        self.manager = kwargs['manager']
        self.digits = kwargs['digit']
        self.digit2 = None
        self.set = False
        self.digitFileBase = 'numbers/{0}.png'
        BaseDialog.__init__(self,*args,**kwargs)

    def onInit(self):
        BaseDialog.onInit(self)
        self.setProperty('digit1',self.digitFileBase.format(self.digits))

    def onAction(self, action):
        try:
            if action == xbmcgui.ACTION_SELECT_ITEM:
                self.finish()
            else:
                self.handleDigit(action)
        finally:
            BaseDialog.onAction(self,action)

    def handleDigit(self, action):
        if  action.getId() >= xbmcgui.REMOTE_0 and action.getId() <= xbmcgui.REMOTE_9:
            if self.digit2:
                digit3 = str(action.getId() - 58)
                self.digits += digit3
                self.setProperty('digit3',self.digitFileBase.format(digit3))
                self.setProperty('number',self.digits)
                xbmc.sleep(100)
                self.finish()
            else:
                self.digit2 = str(action.getId() - 58)
                self.digits += self.digit2
                self.setProperty('digit2',self.digitFileBase.format(self.digit2))

    def finish(self):
        self.digits = int(self.digits)
        self.set = True
        for channel in self.manager.channels if util.getSetting('mode') == 'EPG' else self.manager.channels1:
            if channel['ID'] == str(self.digits):
                self.manager.player.play(channel)
                break
        self.close()
