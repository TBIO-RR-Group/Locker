#file:SSOApache.pm
#--------------------------
  package SSOApache;
  
  use strict;
  use warnings;
  use Data::Dumper;
  use LWP::UserAgent;
  use HTTP::Request;
  use Cache::FastMmap;

  use APR::Table ();  
  use Apache2::RequestRec ();
  use Apache2::Connection ();
  use Apache2::RequestUtil ();
  
  use Apache2::Const -compile => qw(FORBIDDEN OK REDIRECT);

  use constant SHARE_FILE => '/tmp/.cache_fastmmap_sharefile';

  our $requiredUsers = {};
  my $ssoParams = {};
  while (my $curLine = <DATA>) {      
      $curLine = rem_ws($curLine);
      next if ($curLine =~ m/^\#/);
      my @lineParts = split /\t/, $curLine;
      if (scalar @lineParts <= 1) {
	  $requiredUsers->{$lineParts[0]} = 1;
      } else {
	  $ssoParams->{$lineParts[0]} = $lineParts[1];
      }
  }

  my $SSO_SESSION_COOKIE_NAME = $ssoParams->{'SSO_SESSION_COOKIE_NAME'};
  my $REDIRECT_TARGET_ARGNAME = $ssoParams->{'REDIRECT_TARGET_ARGNAME'};

  our $validatedCookies = Cache::FastMmap->new('share_file' => SHARE_FILE);

  # Get browser-like headers required for ForgeRock validation
  sub get_browser_headers {
      return (
          'User-Agent' => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
          'Accept' => 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
          'Accept-Encoding' => 'gzip, deflate, br, zstd',
          'Accept-Language' => 'en-US,en;q=0.9,ko;q=0.8',
          'Cache-Control' => 'no-cache',
          'Pragma' => 'no-cache',
          'Sec-Ch-Ua' => '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
          'Sec-Ch-Ua-Mobile' => '?0',
          'Sec-Ch-Ua-Platform' => '"Windows"',
          'Sec-Fetch-Dest' => 'document',
          'Sec-Fetch-Mode' => 'navigate',
          'Sec-Fetch-Site' => 'none',
          'Sec-Fetch-User' => '?1',
          'Upgrade-Insecure-Requests' => '1'
      );
  }
  
  sub handler {
      my $r = shift;

#logit("Processing ForgeRock authentication\n");

      my $cookies = $r->headers_in()->{Cookie};
      my $cookies_hashref = parseCookies($cookies);

      my $hostport = join ':', $r->get_server_name, $r->get_server_port;
      my $full_url = "http://" . $hostport . $r->unparsed_uri();
      my $location =  $ssoParams->{'REDIRECT_URL'} . "?${REDIRECT_TARGET_ARGNAME}=" . uri_encode($full_url);

      if (!defined($cookies_hashref->{$SSO_SESSION_COOKIE_NAME})) {
#logit("No $SSO_SESSION_COOKIE_NAME, redirecting\n");
         $r->headers_out->set(Location => $location);
         return Apache2::Const::REDIRECT;
      }

      removeInvalidCookies();

      my $validatedCookieVals = $validatedCookies->get($cookies_hashref->{$SSO_SESSION_COOKIE_NAME});
      if (defined($validatedCookieVals)) {
	  if ($requiredUsers->{$validatedCookieVals->[2]}) {
	      return Apache2::Const::OK;
	  } else {
#	      logit("Forbidden1\n");
	      return Apache2::Const::FORBIDDEN;
	  }
      }

      my $pass = 0;

      my $ua = LWP::UserAgent->new();
      my $req = HTTP::Request->new('GET', $ssoParams->{'VALIDATE_URL'});
      
      # Set cookie
      $req->header('Cookie', "${SSO_SESSION_COOKIE_NAME}=" . $cookies_hashref->{$SSO_SESSION_COOKIE_NAME});
      
      # Add browser-like headers required for ForgeRock validation
#logit("Adding ForgeRock browser headers\n");
      my %browser_headers = get_browser_headers();
      for my $header_name (keys %browser_headers) {
          $req->header($header_name, $browser_headers{$header_name});
      }
      
      my $res = $ua->request($req);
      
      if ($res->is_success()) {
	  my $resContent = $res->content;
	  if (empty($resContent)) { $resContent = "" }
	  my @resLines = map { rem_ws($_); } split /\n/, $resContent;
	  if ((scalar @resLines <= 0) || ($resLines[0] ne 'Success')) {
#logit("did not validate, redirecting\n");
#logit(Dumper(\@resLines) . "\n");
#logit($res->content . "\n");
             $r->headers_out->set(Location => $location);
             return Apache2::Const::REDIRECT;
	  }
	  my $validateVals = {};
	  map { if (m/^([^\=]+)\=(.+)$/) { $validateVals->{$1} = $2; } } @resLines;
	  if ($requiredUsers->{$validateVals->{'User'}}) {
	      $pass = 1;
	      $validatedCookies->set($cookies_hashref->{$SSO_SESSION_COOKIE_NAME},[$validateVals->{"TTL"},time(),$validateVals->{"User"}]);
#	      logit("Added new ForgeRock Cookie:\n" . $cookies_hashref->{$SSO_SESSION_COOKIE_NAME} . "\n" . $validateVals->{"TTL"}. "\n" . $validateVals->{"User"} . "\n");
	  }
      }

#logit("pass = $pass\n");  
      return $pass
          ? Apache2::Const::OK
          : Apache2::Const::FORBIDDEN;
  }

  #Got from here (orig called urlize): http://code.activestate.com/recipes/577450-perl-url-encode-and-decode/
  sub uri_encode {
      my ($rv) = @_;
      $rv =~ s/([^A-Za-z0-9])/sprintf("%%%2.2X", ord($1))/ge;
      return $rv;
  }

  sub removeInvalidCookies {

      my $currentEpochSecs = time();
      my @allSmsessionArr = $validatedCookies->get_keys();
#      logit("Before NUM KEYS: " . scalar(@allSmsessionArr) . "\n");
      foreach my $smsessionCookie (@allSmsessionArr) {
	  my $cookieTimeVals = $validatedCookies->get($smsessionCookie);
	  if (!defined($cookieTimeVals) || (scalar @$cookieTimeVals < 3)) { $validatedCookies->remove($smsessionCookie); }
	  my ($initTtlSecs, $initEpochSecs) = @$cookieTimeVals;
	  my $secsDiff = $currentEpochSecs - $initEpochSecs;
	  my $remainingTtlSecs = $initTtlSecs - $secsDiff;
	  if ($remainingTtlSecs <= 0) { $validatedCookies->remove($smsessionCookie); }
      }
      @allSmsessionArr = $validatedCookies->get_keys();
#      logit("After NUM KEYS: " . scalar(@allSmsessionArr) . "\n");

  }


  sub logit {
	
     my ($msg) = @_;

     open F, ">>/tmp/AKSlog.txt";
     print F "PROC $$ : $msg";
     close(F);
}


#Or could use:
#      use Cookie::Baker;
#      my $cookies_hashref = crush_cookie($r->headers_in()->{Cookie});
  sub parseCookies {

      my ($cookies) = @_;

      if (empty($cookies)) { $cookies = ""; }

      my $cookiesHash = {};
      my @cookiesSplit = split /\s*;\s*/, $cookies;
      foreach my $curCookie (@cookiesSplit) {
	  if ($curCookie =~ m/^(.+)=(.+)$/i) {
	      my $cname = $1;
	      my $cvalue = $2;
	      $cname = rem_ws($cname);
	      $cvalue = rem_ws($cvalue);
	      $cookiesHash->{$cname} = $cvalue;
	  }
      }
      return($cookiesHash);
  }

  sub rem_ws {
      my ($inVal) = @_;

      if (!defined($inVal)) { return(""); }
      $inVal =~ s/^\s+//;
      $inVal =~ s/\s+$//;
      return($inVal);
}

  sub empty {
      my ($inVal) = @_;

      if (!defined($inVal)) { return(1); }
      if ($inVal =~ m/^\s*$/) { return(1); }
      return(0);
}
  
1;

###Add __DATA__ section at bottom listing users who can access, e.g.:
#__DATA__
#smitha26
#russom
#rens
