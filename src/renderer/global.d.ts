import type {MailOperationsAPI} from '../shared/mail-operations';
import type {MailWorkspaceAPI} from '../shared/mail-workspace';
import type {PreferencesAPI} from '../shared/preferences';
import type {MailAPI} from '../shared/mail';
import type {DesktopAPI} from '../shared/contracts';
import type {WidgetAPI} from '../shared/widget';
declare global{interface Window{mailOperations:MailOperationsAPI;mailWorkspace:MailWorkspaceAPI;preferences?:PreferencesAPI;mail:MailAPI;desktop:DesktopAPI;widget?:WidgetAPI}}
