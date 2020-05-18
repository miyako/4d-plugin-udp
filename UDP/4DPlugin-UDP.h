/* --------------------------------------------------------------------------------
 #
 #	4DPlugin-UDP.h
 #	source generated by 4D Plugin Wizard
 #	Project : UDP
 #	author : miyako
 #	2020/05/18
 #  
 # --------------------------------------------------------------------------------*/

#ifndef PLUGIN_UDP_H
#define PLUGIN_UDP_H

#if _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <ws2ipdef.h>
#endif

#include <time.h>

#include "4DPluginAPI.h"
#include "4DPlugin-JSON.h"
#include "C_LONGINT.h"
#include "C_TEXT.h"

#if VERSIONMAC
#include <getopt.h>
#include <arpa/inet.h>
#else
#define option option_a
#define getopt_long getopt_long_a
#define optarg optarg_a
#define close closesocket
#pragma comment(lib, "Ws2_32.lib")
#endif
#include <stdio.h>
#include <stdlib.h>
#include <vector>

#if VERSIONMAC
typedef int sock_t;
typedef int broadcast_t;
typedef socklen_t addrlen_t;
typedef ssize_t recvlen_t;
#else
typedef SOCKET sock_t;
typedef char broadcast_t;
typedef int addrlen_t;
typedef int recvlen_t;
#endif

#define CMD_Get_database_localization 1009
#define eDL_Default_localization 0

#pragma mark -

void UDP_Get_server_list(PA_PluginParameters params);

#endif /* PLUGIN_UDP_H */
